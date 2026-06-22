import json
import psycopg2
from psycopg2 import sql
import requests

def verify_external_db_connection(db_type, config):
    """
    Tests the connection parameters to an external database (PostgreSQL, Elasticsearch, OpenSearch).
    Returns (success: bool, message: str).
    """
    host = config.get("host")
    port = config.get("port")
    database = config.get("database")  # index name for ES/OpenSearch
    user = config.get("user")
    password = config.get("password")
    ssl_mode = config.get("ssl_mode", "disable")

    if not host or not port or not database:
        return False, "Host, Port, and Database/Index name are required."

    try:
        port_num = int(port)
    except ValueError:
        return False, "Port must be a valid number."

    if db_type == "postgres":
        try:
            # Test PostgreSQL Connection
            # sslmode options: disable, allow, prefer, require, verify-ca, verify-full
            conn = psycopg2.connect(
                host=host,
                port=port_num,
                database=database,
                user=user if user else None,
                password=password if password else None,
                sslmode=ssl_mode if ssl_mode else "disable",
                connect_timeout=5
            )
            # Run simple query
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
            
            # Check table or check if we can create it
            table_name = config.get("table_or_index") or "notifications"
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                );
            """, (table_name,))
            table_exists = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()

            status_msg = f"Connected successfully! Table '{table_name}' "
            if table_exists:
                status_msg += "already exists and is ready."
            else:
                status_msg += "does not exist yet (will be auto-created on first insert)."
            
            return True, status_msg

        except Exception as e:
            return False, f"PostgreSQL Connection failed: {str(e)}"

    elif db_type in ["elasticsearch", "opensearch"]:
        try:
            # Build REST API URL
            proto = "https" if ssl_mode in ["require", "yes", "true", "verify-ca", "verify-full"] else "http"
            base_url = f"{proto}://{host}:{port_num}"
            
            auth = (user, password) if user else None
            
            # Test connectivity to root node
            # We use verify=False so self-signed certs (common in local setups) don't fail,
            # but we show a warning if verification is ignored.
            res = requests.get(
                base_url, 
                auth=auth, 
                timeout=5, 
                verify=False
            )
            
            if res.status_code not in [200, 201]:
                return False, f"Server returned status code {res.status_code}: {res.text[:200]}"
            
            # Check if index exists or test writing privileges if index is given
            # Elasticsearch index status endpoint: GET /<index>
            index_url = f"{base_url}/{database}"
            index_res = requests.get(index_url, auth=auth, timeout=5, verify=False)
            
            db_label = "Elasticsearch" if db_type == "elasticsearch" else "OpenSearch"
            if index_res.status_code == 200:
                return True, f"Connected to {db_label}! Index '{database}' exists and is ready."
            elif index_res.status_code == 404:
                return True, f"Connected to {db_label}! Index '{database}' does not exist yet (will be auto-created)."
            else:
                return True, f"Connected to {db_label}! Index verification status: {index_res.status_code}."

        except Exception as e:
            db_label = "Elasticsearch" if db_type == "elasticsearch" else "OpenSearch"
            return False, f"{db_label} Connection failed: {str(e)}"

    else:
        return False, f"Unsupported database type: {db_type}"


def push_to_external_db(db_type, config, payload):
    """
    Pushes notification payload to the external database.
    Raises exception on failure.
    """
    host = config.get("host")
    port = int(config.get("port", 0))
    database = config.get("database")  # index name for ES/OpenSearch
    user = config.get("user")
    password = config.get("password")
    ssl_mode = config.get("ssl_mode", "disable")
    table_or_index = config.get("table_or_index") or "notifications"

    if db_type == "postgres":
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user if user else None,
            password=password if password else None,
            sslmode=ssl_mode if ssl_mode else "disable",
            connect_timeout=10
        )
        try:
            cursor = conn.cursor()
            # 1. Create table if not exists
            # We use identifier formatting to avoid SQL injection on table name
            # We validate table_name is alphanumeric + underscores only first
            cleaned_table_name = "".join(c for c in table_or_index if c.isalnum() or c == "_")
            if not cleaned_table_name:
                cleaned_table_name = "notifications"

            create_query = f"""
                CREATE TABLE IF NOT EXISTS {cleaned_table_name} (
                    id SERIAL PRIMARY KEY,
                    notification_id INTEGER,
                    title VARCHAR(255) NOT NULL,
                    category VARCHAR(50),
                    body TEXT,
                    organization_name VARCHAR(255),
                    state VARCHAR(100),
                    seo_url VARCHAR(255),
                    meta_description TEXT,
                    pushed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            cursor.execute(create_query)
            conn.commit()

            # 2. Insert record
            insert_query = f"""
                INSERT INTO {cleaned_table_name} (
                    notification_id, title, category, body, organization_name, state, seo_url, meta_description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """
            cursor.execute(insert_query, (
                payload.get("notification_id"),
                payload.get("title"),
                payload.get("category"),
                payload.get("body"),
                payload.get("organization_name"),
                payload.get("state"),
                payload.get("seo_url"),
                payload.get("meta_description")
            ))
            conn.commit()
            cursor.close()
        finally:
            conn.close()

    elif db_type in ["elasticsearch", "opensearch"]:
        proto = "https" if ssl_mode in ["require", "yes", "true", "verify-ca", "verify-full"] else "http"
        # Index document URL: POST /<index_name>/_doc/<id>
        url = f"{proto}://{host}:{port}/{database}/_doc/{payload.get('notification_id')}"
        
        auth = (user, password) if user else None
        
        headers = {"Content-Type": "application/json"}
        
        # Format dates/datetimes nicely for JSON/ES
        doc_payload = {
            "notification_id": payload.get("notification_id"),
            "title": payload.get("title"),
            "category": payload.get("category"),
            "body": payload.get("body"),
            "organization_name": payload.get("organization_name"),
            "state": payload.get("state"),
            "seo_url": payload.get("seo_url"),
            "meta_description": payload.get("meta_description"),
            "pushed_at": payload.get("pushed_at") or ""
        }
        
        res = requests.post(
            url,
            json=doc_payload,
            auth=auth,
            headers=headers,
            timeout=10,
            verify=False
        )
        
        if res.status_code not in [200, 201]:
            raise Exception(f"Failed to index document in {db_type.upper()}: Status {res.status_code} - {res.text}")
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

(function($) {
	
	var direction =  getUrlParams('dir');
	if(direction != 'rtl')
	{direction = 'ltr'; }

    var stored = {};
    try {
        stored = JSON.parse(localStorage.getItem('dezSettings') || '{}');
    } catch(e) {}

	var dezSettingsOptions = {
		typography: stored.typography || "poppins",
		version: stored.version || "light",
		layout: stored.layout || "Vertical",
		headerBg: stored.headerBg || "color_1",
		navheaderBg: stored.navheaderBg || "color_1",
		sidebarBg: stored.sidebarBg || "color_1",
		sidebarStyle: stored.sidebarStyle || "full",
		sidebarPosition: stored.sidebarPosition || "fixed",
		headerPosition: stored.headerPosition || "fixed",
		containerLayout: stored.containerLayout || "full",
		direction: stored.direction || direction,
        primary: stored.primary || "color_1"
	};
		
	new dezSettings(dezSettingsOptions); 

	jQuery(window).on('resize',function(){
		new dezSettings(dezSettingsOptions); 
	});

})(jQuery);
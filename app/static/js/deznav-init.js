(function($) {
	
	var direction =  getUrlParams('dir');
	if(direction != 'rtl')
	{direction = 'ltr'; }

	var dezSettingsOptions = {
		typography: "poppins",
		version: "light",
		layout: "Vertical",
		headerBg: "color_1",
		navheaderBg: "color_1",
		sidebarBg: "color_1",
		sidebarStyle: "full",
		sidebarPosition: "fixed",
		headerPosition: "fixed",
		containerLayout: "full",
		direction: direction
	};
		
	new dezSettings(dezSettingsOptions); 

	function debounce(func, delay) {
		var timeout;
		return function() {
			var context = this;
			var args = arguments;
			clearTimeout(timeout);
			timeout = setTimeout(function() {
				func.apply(context, args);
			}, delay);
		};
	}

	jQuery(window).on('resize', debounce(function(){
		new dezSettings(dezSettingsOptions); 
	}, 150));

})(jQuery);
/*
 * Map an individual item with GeoJSON
 */
var polyStyle = {
	"color": "#ff7800",
	"weight": 2,
	"opacity": 0.85,
	"fillOpacity": 0.5
 };
 
function search_map(json_url) {
	
	var geodeep = 6; // default geo-facet tile depth
	var rows = 20; // default number of rows
	var tile_constrained = false;
	var map_box_token = "pk.eyJ1IjoiZWthbnNhIiwiYSI6IlZFQ1RfM3MifQ.KebFObTZOeh9pDHM_yXY4g";
	
	this.json_url = json_url; // base url for geo-json requests
	this.json_url = this.json_url.replace('&amp;', '&');
	var url_parts = getJsonFromUrl(json_url);
	if (url_parts['disc-geotile']) {
		//geodeep = url_parts['disc-geotile'].length + 4;
		geodeep = 4;
		tile_constrained = true;
	}
	else{
		if (url_parts['geodeep']) {
			geodeep = url_parts['geodeep'];
			
		}
		else{
			var check_url = this.json_url.replace('.json', '');
			var url_ex = check_url.split('/sets/');
			if (url_ex.length > 1) {
				var after_sets = url_ex[1];
				if (after_sets.length > 0) {
					geodeep = 8;
					var after_sets = url_ex[1];
					var slash_count = (after_sets.match(/\//g) || []).length;
					if (slash_count > 0) {
						geodeep += slash_count + 2;
					}
				}
			}
		}
	}
	
	map = L.map('map').setView([45, 0], 2); //map the map
	map.json_url = this.json_url
	map.geodeep = geodeep;
	map.rows = rows;
	map.fit_bounds = false;
	map.geojson_facets = false;  //geojson data for facet regions
	map.geojson_records = false; //geojson data for records
	if (map.geodeep > 6 || tile_constrained) {
		map.fit_bounds = true;
	}
	if (map.geodeep > 20) {
		map.geodeep = 20;
	}
	var bounds = new L.LatLngBounds();
	var osmTiles = L.tileLayer('http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
		attribution: '&copy; <a href="http://osm.org/copyright">OpenStreetMap</a> contributors'
	});
   
    /*
	var mapboxTiles = L.tileLayer('http://api.tiles.mapbox.com/v3/ekansa.map-tba42j14/{z}/{x}/{y}.png', {
		attribution: '&copy; <a href="http://MapBox.com">MapBox.com</a> '
	});
	*/
	var mapboxPencil = L.tileLayer('http://api.tiles.mapbox.com/v4/mapbox.pencil/{z}/{x}/{y}.png?access_token=' + map_box_token, {
		attribution: '&copy; <a href="http://MapBox.com">MapBox.com</a> '
	});
	
	var mapboxDark = L.tileLayer('http://api.tiles.mapbox.com/v4/mapbox.dark/{z}/{x}/{y}.png?access_token=' + map_box_token, {
		attribution: '&copy; <a href="http://MapBox.com">MapBox.com</a> '
	});
   
	var ESRISatelliteTiles = L.tileLayer('http://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
		attribution: '&copy; <a href="http://services.arcgisonline.com/">ESRI.com</a> '
	});
   
	var gmapRoad = new L.Google('ROADMAP');
	var gmapSat = new L.Google('SATELLITE');
	var gmapTer = new L.Google('TERRAIN');
   
	var baseMaps = {
		"Google-Terrain": gmapTer,
		"Google-Satellite": gmapSat,
		"ESRI-Satellite": ESRISatelliteTiles,
		"Google-Roads": gmapRoad,
		"OpenStreetMap": osmTiles,
		"Pencil": mapboxPencil,
		"Dark": mapboxDark,
	};
  
	map._layersMaxZoom = 20;
	L.control.layers(baseMaps).addTo(map);
	map.addLayer(gmapSat);
	
	var region_layer = false
	map.render_region_layer = function (){
		// does the work of rendering a region facet layer
		if (map.geojson_facets != false) {
			/*
			 * Show current layer type
			 */
			var act_dom_id = "map-title";
			document.getElementById(act_dom_id).innerHTML = "Map of Counts by Region";
			var act_dom_id = "map-title-suffix";
			document.getElementById(act_dom_id).innerHTML = "";
			/*
			 * Loop through features to get the range of counts.
			 */
			var max_value = 1;
			var min_value = 0;
			for (var i = 0, length = map.geojson_facets.features.length; i < length; i++) {
				feature = map.geojson_facets.features[i];
				if (feature.count > max_value) {
					max_value = feature.count;
				}
				if (i < 1) {
					min_value = feature.count;
				}
				else{
					if (feature.count < min_value) {
						min_value = feature.count;
					}
				}
			}
			region_layer = L.geoJson(map.geojson_facets,
						   {
								style: function(feature){
										// makes colors, opacity for each feature
										var style_obj = new numericStyle();
										style_obj.min_value = min_value;
										style_obj.max_value = max_value;
										style_obj.act_value = feature.count;
										var hex_color = style_obj.generate_hex_color();
										var fill_opacity = style_obj.generate_opacity();
										return {color: hex_color,
												fillOpacity: fill_opacity,
												weight: 2}
									    },
								onEachFeature: on_each_region_feature
									 });
			var jsonGroup = new L.FeatureGroup(region_layer); 
			if (map.fit_bounds) {
				map.fitBounds(bounds);
				//map.fitBounds(jsonGroup.getBounds());
			}
			region_layer.addTo(map);
		}
	}
	
	function on_each_region_feature(feature, layer){
		/*
		 * For handeling facet region features
		 */
		feature.re_color = function(min_value, max_value){
			// make a function for each feature to assign new colors
			var style_obj = new numericStyle();
			style_obj.min_value = min_value;
			style_obj.max_value = max_value;
			style_obj.act_value = feature.count;
			var hex_color = style_obj.generate_hex_color();
			var fill_opacity = style_obj.generate_opacity();
			layer.setStyle({
				color: hex_color,
				fillOpacity: fill_opacity
			});
		}
		if (feature.properties) {
			var popupContent = "<div> This discovery region has " + feature.count;
			popupContent += " items";

			popupContent += ". ";
			if(feature.properties.href){
				var use_href = removeURLParameter(feature.properties.href, 'response');
				use_href = removeURLParameter(use_href, 'geodeep');
				var next_deep = map.geodeep + 5;
				if (next_deep > 20) {
					next_deep = 20;
				}
				use_href += "&geodeep=" + next_deep;
				popupContent += "<a href='" + use_href + "'>Click here</a> to filter by this region."
			}
			popupContent += "</div>";
			layer.bindPopup(popupContent);
		}
		var newbounds = layer.getBounds();
		bounds.extend(newbounds.getSouthWest());
		bounds.extend(newbounds.getNorthEast());
	}
	
	map.get_geojson_regions = function (){
		/*
		* Show current layer type
		*/
		var act_dom_id = "map-title";
		var loading = "<img height=\"20\" width=\"20\"  src=\"" + base_url + "/static/oc/images/ui/waiting.gif\" alt=\"Loading icon...\" />";
		loading += " Loading Regions...";
		document.getElementById(act_dom_id).innerHTML =loading;
		var act_dom_id = "map-title-suffix";
		document.getElementById(act_dom_id).innerHTML = "";	
		//do the ajax request
		$.ajax({
			type: "GET",
			url: map.json_url,
			dataType: "json",
			data: {
				response: "geo-facet",
				geodeep: map.geodeep},
			success: function(data) {
				map.geojson_facets = data;
				map.render_region_layer();
			}
		})
	}

	this.region_layer = region_layer;
	this.map = map;
}


function removeURLParameter(url, parameter) {
    //prefer to use l.search if you have a location/link object
    var urlparts= url.split('?');   
    if (urlparts.length>=2) {

        var prefix= encodeURIComponent(parameter)+'=';
        var pars= urlparts[1].split(/[&;]/g);

        //reverse iteration as may be destructive
        for (var i= pars.length; i-- > 0;) {    
            //idiom for string.startsWith
            if (pars[i].lastIndexOf(prefix, 0) !== -1) {  
                pars.splice(i, 1);
            }
        }

        url= urlparts[0]+'?'+pars.join('&');
        return url;
    } else {
        return url;
    }
}

function getJsonFromUrl() {
	// parse a URL
	var query = location.search.substr(1);
	var result = {};
	query.split("&").forEach(function(part) {
		var item = part.split("=");
		result[item[0]] = decodeURIComponent(item[1]);
	});
	return result;
}
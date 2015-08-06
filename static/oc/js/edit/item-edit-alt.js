/*
 * Functions to edit an item
 */
function itemEdit(item_type, item_uuid){
	this.project_uuid = project_uuid;
	this.item_uuid = item_uuid;
	this.item_type = item_type;
	this.fields = [];
	this.obj_name = 'edit_item';
	this.panels = [];
	this.getItemJSON = function(){
		/* gets the item JSON-LD from the server */
		this.item_json_ld_obj = new item_object(this.item_type, this.item_uuid);
		var url = this.make_url("/" + this.item_type + "/" + encodeURIComponent(this.item_json_ld_obj.uuid) + ".json");
		return $.ajax({
			type: "GET",
			url: url,
			context: this,
			dataType: "json",
			success: this.getItemJSONDone,
			error: function (request, status, error) {
				alert('Item JSON retrieval failed, sadly. Status: ' + request.status);
			}
		});
	}
	this.getItemJSONDone = function(data){
		/* the JSON-LD becomes this object's data */
		this.item_json_ld_obj.data = data;
		this.show_existing_data();
		console.log(this.fields);
	}
	this.show_existing_data = function(){
		if (this.item_json_ld_obj != false) {
			if (this.item_json_ld_obj.data != false) {
				// get observation data
				this.show_observation_data();
				this.fields_postprocess();
			}
		}
	}
	this.show_observation_data = function(){
		// first get information on the predicates from the JSON-LD context
		this.item_json_ld_obj.getPredicates();
		var observations = this.item_json_ld_obj.getObservations();
		var number_obs = observations.length;
		var obs_html_list = [];
		for (var obs_num = 0; obs_num < number_obs; obs_num++) {
			var obs = observations[obs];
			var fields_html = '';
			for (var predicate_uuid in this.item_json_ld_obj.predicates_by_uuid) {
				var pred_item = this.item_json_ld_obj.predicates_by_uuid[predicate_uuid];
				var values_obj = this.item_json_ld_obj.getObsValuesByPredicateUUID(obs_num, predicate_uuid);
				if (values_obj.length > 0) {
					// this particular observation has a predicate with values
					var field = new edit_field();
					field.id = this.fields.length;
					field.project_uuid = this.project_uuid;
					field.parent_obj_name = this.obj_name;
					field.obj_name = 'fields[' + field.id + ']';
					field.add_new_data_row = true;
					field.edit_new = false;
					field.edit_uuid = this.item_uuid;
					field.item_type = this.item_type;
					field.label = pred_item.label;
					field.predicate_uuid = predicate_uuid;
					field.data_type = pred_item.data_type;
					field.values_obj = this.item_json_ld_obj.getValuesByPredicateUUID(predicate_uuid);
					var field_html = field.make_field_html();
					fields_html += field_html;
					this.fields.push(field);
				}
			}
			if (fields_html.length > 1) {
				if (number_obs > 1) {
					// we have multiple observations, so put them into collapsable panels
					var panel_num = this.panels.length;
					var obs_panel = new panel(panel_num);
					obs_panel.title_html = fgroup.label;
					obs_panel.body_html = fields_html;
					var observation_html = obs_panel.make_html();
					obs_html_list.push(observation_html);
				}
				else{
					obs_html_list.push(fields_html);
				}
			}// end case with an observation with data
		}//end loop through observations
		if (obs_html_list.length > 0) {
			// we have observation data, now fix to the appropriate dom element.
			document.getElementById('obs-fields').innerHTML = obs_html_list.join("\n");
		}
	}//end function for observation data
	
	this.fields_postprocess = function(){
		//set up trees, calendars, etc. all the functions
		//that need to be done after the fields have been added ot the DOM
		for (var i = 0, length = this.fields.length; i < length; i++) {
			var field = this.fields[i];
			field.postprocess();
		}
	}
	
	
	this.make_url = function(relative_url){
	//makes a URL for requests, checking if the base_url is set	
		 //makes a URL for requests, checking if the base_url is set
		var rel_first = relative_url.charAt(0);
		if (typeof base_url != "undefined") {
			var base_url_last = base_url.charAt(-1);
			if (base_url_last == '/' && rel_first == '/') {
				return base_url + relative_url.substring(1);
			}
			else{
				return base_url + relative_url;
			}
		}
		else{
			if (rel_first == '/') {
				return '../..' + relative_url;
			}
			else{
				return '../../' + relative_url;
			}
		}
	}
	this.make_loading_gif = function(message){
		var src = this.make_url('/static/oc/images/ui/waiting.gif');
		var html = [
			'<div class="row">',
			'<div class="col-sm-1">',
			'<img alt="loading..." src="' + src + '" />',
			'</div>',
			'<div class="col-sm-11">',
			message,
			'</div>',
			'</div>'
			].join('\n');
		return html;
	}
}
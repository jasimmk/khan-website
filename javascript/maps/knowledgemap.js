
var KnowledgeMap = {

    map: null,
    dictNodes: {},
    dictEdges: [],
    widthPoints: 200,
    heightPoints: 120,
    latLngHome: new google.maps.LatLng(0.471, 0.9846),
    latLngBounds: null,
    options: {
                getTileUrl: function(coord, zoom) {
                    return "/images/black_tile.png";
                },
                tileSize: new google.maps.Size(256, 256),
                maxZoom: 10,
                minZoom: 8,
                isPng: true
    },

    init: function() {

        this.map = new google.maps.Map(document.getElementById("map_canvas"), {
            mapTypeControl: false,
            streetViewControl: false
        });

        var knowledgeMapType = new google.maps.ImageMapType(this.options);
        this.map.mapTypes.set('knowledge', knowledgeMapType);
        this.map.setMapTypeId('knowledge');

        this.map.setCenter(this.latLngHome);
        this.map.setZoom((this.options.minZoom + this.options.maxZoom) / 2);

        var widthHalf = this.widthPoints / 2;
        var heightHalf = this.heightPoints / 2;
        this.latLngBounds = new google.maps.LatLngBounds(new google.maps.LatLng(-1 * widthHalf, -1 * heightHalf), 
                new google.maps.LatLng(widthHalf, heightHalf)),
        google.maps.event.addListener(this.map, "center_changed", function(){KnowledgeMap.restrictBounds();});

        this.layoutGraph();
    },

    layoutGraph: function() {
        for (var key in this.dictNodes)
        {
            this.drawMarker(this.dictNodes[key]);
        }

        for (var key in this.dictEdges)
        {
            var rgTargets = this.dictEdges[key];
            for (var ix = 0; ix < rgTargets.length; ix++)
            {
                this.drawEdge(this.dictNodes[key], this.dictNodes[rgTargets[ix]]);
            }
        }
    },

    addNode: function(node) {
        this.dictNodes[node.id] = node;
    },

    addEdge: function(source, target) {
        if (!this.dictEdges[source]) this.dictEdges[source] = [];
        var rg = this.dictEdges[source];
        rg[rg.length] = target;
    },

    drawEdge: function(nodeSource, nodeTarget) {

        var coordinates = [
            nodeSource.latLng,
            nodeTarget.latLng
        ];

        var line = new google.maps.Polyline({
            path: coordinates,
            strokeColor: "#E5ECF9",
            strokeOpacity: 1.0,
            strokeWeight: 3
        });

        line.setMap(this.map);
    },

    drawMarker: function(node) {

        var offset = 0.25;

        node.latLng = new google.maps.LatLng(
            (node.v_position - 1) * offset,
            (node.h_position - 1) * offset
        );

        var icon = (node.status == "Proficient") ? "/images/full-star.png" : "/images/empty-star.png";
        var labelClass = "nodeLabel nodeLabel" + node.status;

        var markerImage = new google.maps.MarkerImage(icon, null, null, new google.maps.Point(12, 14), null);

        var marker = new MarkerWithLabel({
            position: node.latLng,
            map: this.map,
            icon: markerImage,
            labelContent: node.name,
            labelAnchor: new google.maps.Point(40, -13),
            labelClass: labelClass
        });

        node.marker = marker;
        google.maps.event.addListener(marker, "click", function(){KnowledgeMap.onNodeClick(node);});
    },

    onNodeClick: function(node) {
        window.location = node.url;
    },

    restrictBounds: function() {

        var center = this.map.getCenter();

        if (this.latLngBounds.contains(center)) return;

        var C = center;
        var X = C.lng();
        var Y = C.lat();

        var AmaxX = this.latLngBounds.getNorthEast().lng();
        var AmaxY = this.latLngBounds.getNorthEast().lat();
        var AminX = this.latLngBounds.getSouthWest().lng();
        var AminY = this.latLngBounds.getSouthWest().lat();

        if (X < AminX) {X = AminX;}
        if (X > AmaxX) {X = AmaxX;}
        if (Y < AminY) {Y = AminY;}
        if (Y > AmaxY) {Y = AmaxY;}

        this.map.setCenter(new google.maps.LatLng(Y,X));
    },
};

var infowindow1 = new google.maps.InfoWindow({
    content: "<h3>Addition 1</h3><p>Energy Points: fuck yeah<br/><br/><input type='button' value='Start this shiz'/></p>"
});

var infowindow2 = new google.maps.InfoWindow({
    content: "<h3>Subtraction 1</h3><p>Energy Points: fuck yeah<br/><br/><input type='button' value='Start this shiz'/></p>"
    });


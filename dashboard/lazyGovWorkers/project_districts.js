// Project the district GeoJSON with the same Albers USA settings as the state map -> SVG path strings.
// Run: NODE_PATH=/path/to/node_modules node dashboard/lazyGovWorkers/project_districts.js
const fs = require("fs"), path = require("path");
const { geoPath, geoAlbersUsa } = require("d3-geo");
const gj = JSON.parse(fs.readFileSync(path.join(__dirname, "cd120_simplified.geojson")));
const gp = geoPath(geoAlbersUsa().scale(1300).translate([487.5, 305])).digits(1);
const districts = gj.features.map(f => ({ key: f.properties.key, state: f.properties.state, d: gp(f) })).filter(x => x.d);
fs.writeFileSync(path.join(__dirname, "districts_paths.json"), JSON.stringify(districts));
console.log(districts.length, "of", gj.features.length, "projected");

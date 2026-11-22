// One-off: project US state outlines (us-atlas) with Albers USA into SVG path strings.
// Run:  NODE_PATH=/path/to/node_modules node dashboard/make_states.js   (needs us-atlas, topojson-client, d3-geo)
const fs = require("fs");
const topo = require("topojson-client");
const { geoPath, geoAlbersUsa } = require("d3-geo");
const us = JSON.parse(fs.readFileSync(require.resolve("us-atlas/states-10m.json")));
const projection = geoAlbersUsa().scale(1300).translate([487.5, 305]);  // fits a 975 x 610 box
const path = geoPath(projection);
const states = topo.feature(us, us.objects.states).features
  .map(f => ({ fips: f.id, name: f.properties.name, d: path(f) }))
  .filter(s => s.d);
const mesh = path(topo.mesh(us, us.objects.states, (a, b) => a !== b));  // interior borders
fs.writeFileSync(process.argv[2] || "dashboard/states_paths.json", JSON.stringify({ width: 975, height: 610, states, borders: mesh }));
console.log(states.length, "states");

"""Tempe OSM -> macro GMNS via osm2gmns (small-MPO golden path, step 1).
tempe.osm.pbf (4 MB) -> gmns_macro/ node.csv + link.csv with default
lanes/speed/capacity filled by facility type."""
import os
import osm2gmns as og

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gmns_macro")

net = og.getNetFromFile(os.path.join(HERE, "tempe.osm.pbf"),
                        link_types=("motorway", "trunk", "primary", "secondary",
                                    "tertiary", "residential"),
                        POI=False)
og.fillLinkAttributesWithDefaultValues(net, default_lanes=True, default_speed=True,
                                       default_capacity=True)
og.consolidateComplexIntersections(net, auto_identify=True)
og.generateNodeActivityInfo(net)
og.outputNetToCSV(net, output_folder=OUT)
print("wrote", OUT)

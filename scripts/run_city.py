import time, json, numpy as np
from PIL import Image
from sunscore import cityrun

t0=time.time()
result = cityrun.run(cell_m=18.0)
print(f"citywide run done in {time.time()-t0:.0f}s")
meta=result["metadata"]; print("grid:",meta["grid"]["shape"],"res:",meta["resolution_m"],"m")

# render annual sun-access over ground cells (north-up image)
acc=result["access"]["annual"]; gm=result["ground_mask"]
img=np.zeros(acc.shape,dtype=np.uint8)
img[gm]=(np.clip(acc[gm],0,1)*255).astype(np.uint8)
Image.fromarray(img).save("data/processed/city_annual_sun_access.png")

for geo in ("ward","community_area","zip"):
    rows=[r for r in result["summaries"][geo] if r["annual_sun_access_pct"] is not None]
    rows.sort(key=lambda r:r["annual_sun_access_pct"])
    print(f"\n=== {geo}: {len(rows)} areas with ground cells ===")
    print("  LEAST sunny (annual):")
    for r in rows[:3]: print(f"    {r['area_id']} {r['display_name'][:22]:22} annual {r['annual_sun_access_pct']}%  summer {r['summer_solstice_sun_access_pct']}%  winter {r['winter_solstice_sun_access_pct']}%")
    print("  MOST sunny:")
    for r in rows[-3:]: print(f"    {r['area_id']} {r['display_name'][:22]:22} annual {r['annual_sun_access_pct']}%  winter {r['winter_solstice_sun_access_pct']}%")

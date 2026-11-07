import json,sys,re
cik,pat=sys.argv[1],sys.argv[2]
d=json.load(open(f"cache/edgar/CIK{int(cik):010d}.json"))
for ns,g in d["facts"].items():
  for t,v in g.items():
    if re.search(pat,t,re.I):
      for unit,u in v["units"].items():
        fy=[x for x in u if x.get("form")=="10-K" and x.get("fp")=="FY"]
        if fy:
          ends=sorted({x["end"] for x in fy})
          print(f"{ns}:{t} [{unit}] {ends[0][:7]}..{ends[-1][:7]} n={len(ends)}")

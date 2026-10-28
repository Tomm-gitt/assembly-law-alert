"""Read-only official-source audit. No HUB writes or messages."""
import json, os, concurrent.futures
from pathlib import Path
import requests
import monitor, status_monitor, post_plenary
OUT=Path("lifecycle-audit");OUT.mkdir(exist_ok=True)
def audit(item):
 result=dict(item);session=requests.Session();session.headers.update(monitor.HEADERS)
 try:
  lookup={"bill_no":item["bill_no"],"bill_name":item["bill_name"]}
  rows={}
  for endpoint,age in [(monitor.MEMBER_BILLS_API,True),(status_monitor.PROCESSED_API,True),(monitor.RECEIPT_API,False)]:
   try:
    row=status_monitor.fetch_matching_row(session,endpoint,lookup,include_age=age)
    if row:rows[endpoint]=row
   except Exception as exc:result.setdefault("errors",[]).append(endpoint+":"+str(exc)[:200])
  result["official_rows"]=rows
  result["exact_found"]=bool(rows)
  if item["hub_stage"]=="공포" or item["bill_no"] in ["2215826","2213019"]:
   url=post_plenary.build_lawmaking_url(item)
   response=session.get(url,timeout=35);response.raise_for_status()
   (OUT/(item["bill_no"]+"-lawmaking.html")).write_bytes(response.content)
   ids=[str(r.get("BILL_ID") or "") for r in rows.values() if r.get("BILL_ID")]
   if ids:
    result["bill_id"]=ids[0]
    result["post"]=post_plenary.fetch_post_plenary_status({**item,"bill_id":ids[0]},session)
  return result
 except Exception as exc:
  result["error"]=str(exc)[:300];return result
 finally:session.close()
if __name__=="__main__":
 items=json.loads(Path("lifecycle_audit_input.json").read_text())
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(audit,items))
 (OUT/"results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
 for r in results:print(json.dumps(r,ensure_ascii=False))
 print("READ_ONLY_AUDIT",len(results),"exact_found",sum(r.get("exact_found",False) for r in results))


import json, requests, monitor

TARGETS = ["2210562","2217933","2202159","2202191","2210560","2214610","2215109","2214614","2206622","2208507","2213264","2200319","2206661"]

def clean(v): return str(v or "").strip()

def rows_for(session, api, bill_no):
    params={"pIndex":"1","pSize":"100","BILL_NO":bill_no}
    if api==monitor.MEMBER_BILLS_API:
        params["AGE"]="22"
    data=monitor.request_api(session, api, params)
    return monitor.parse_rows(data, api)

def main():
    s=requests.Session(); s.headers.update(monitor.HEADERS)
    out={}
    for no in TARGETS:
        found=None
        for api in [monitor.MEMBER_BILLS_API, monitor.RECEIPT_API]:
            try:
                rows=rows_for(s,api,no)
            except Exception as e:
                continue
            for r in rows:
                if clean(r.get("BILL_NO"))==no:
                    bid=clean(r.get("BILL_ID"))
                    if bid:
                        found={"bill_id":bid,"api":api,"bill_name":clean(r.get("BILL_NAME") or r.get("BILL_NM"))}
                        break
            if found: break
        out[no]=found or {}
        print(no, out[no])
    with open("audit_resolved_bill_ids.json","w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)

if __name__=="__main__": main()

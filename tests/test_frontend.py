"""Frontend-Logik (index.html) automatisch prüfen.

1. Node (falls installiert): einzelne Funktionen aus dem Hauptskript herauslösen und prüfen
   (Escaping, Adressprüfung, neue Produkte, Warenkorb ohne entfernte Produkte, 3D-Modell prüfen und aufteilen).
2. Chrome/Chromium headless (falls installiert, gesteuert per Node über das DevTools-Protokoll): echte Seite vom
   Test-Server, die ein fremdes Backend nachstellt (Produkt nur in /products.json mit Sonderzeichen im Namen,
   entferntes Produkt im Warenkorb, kaputtes Modell).
Fehlt Node bzw. Chrome, werden die Tests übersprungen.
"""
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

import harness

NODE = shutil.which("node")
INDEX = harness.ROOT / "core" / "public" / "index.html"


def _chrome():
    for c in (os.environ.get("CHROME_BIN"), shutil.which("google-chrome"), shutil.which("chromium"),
              shutil.which("chromium-browser"), shutil.which("chrome"),
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if c and os.path.exists(c):
            return c
    return None


def _script():
    s = INDEX.read_text(encoding="utf-8")
    return max(re.finditer(r"<script>(.*?)</script>", s, re.S), key=lambda m: len(m.group(1))).group(1)


def _grab(js, start):
    """Top-Level-Definition ab Zeilenanfang `start` bis zur nächsten nicht eingerückten Zeile."""
    m = re.search(r"^" + re.escape(start) + r".*?\n(?=\S)", js, re.S | re.M)
    assert m, start
    return m.group(0)


NODE_TEST = r"""
const assert=require("assert");
const VIAL_H=2.235,MDL_MAX_TRI=200000,MDL_W=1.4;
let P=[{slug:"alt",v:[["5 mg",1]]},{slug:"weg",gone:true,v:[["5 mg",1]]}];
const isCaseItem=()=>false,okCfg=()=>false;
// esc + safeUrl
assert.strictEqual(esc('A <B> & "C"'),"A &lt;B&gt; &amp; &quot;C&quot;");
assert.strictEqual(esc("BPC-157 ≥98 %"),"BPC-157 ≥98 %");
for(const u of ["https://x.example/a.webp","/de/laborzertifikate/"])assert.strictEqual(safeUrl(u),u);
for(const u of ["javascript:alert(1)","//fremd.example/a","http://x.example/a",'https://x/"><img',"data:x",5])assert.strictEqual(safeUrl(u),"");
for(const u of ["/models/a.json","/models/a.json?v=2"])assert.ok(modelUrlOk(u),u);
for(const u of ["//x/a.json","https://x/a.json","/models/../a.json","/a.js","/models/a.json\n"])assert.ok(!modelUrlOk(u),u);
// neue Produkte: gleiche Grenzen wie der Server
const ok={slug:"neu",name:'A <B> & "C"',variants:[{label:"5 mg",price:9.9}]};
assert.ok(newProduct(ok));
assert.strictEqual(newProduct({...ok,slug:"x".repeat(49)}),null);
assert.strictEqual(newProduct({...ok,variants:Array(7).fill({label:"a",price:1})}),null);
assert.strictEqual(newProduct({...ok,variants:[{label:"a",price:"9.9"}]}),null);
assert.strictEqual(newProduct({...ok,slug:"A/B"}),null);
assert.strictEqual(newProduct({...ok,accent:"red"}).cap,"#8A93B8");
assert.deepStrictEqual(newProduct({...ok,tags:["best","x y",'"><b']}).tags,["best"]);
// Warenkorb: entfernte und unbekannte Produkte fallen heraus
assert.deepStrictEqual(Cart.clean([{slug:"alt",vi:0,qty:2},{slug:"weg",vi:0,qty:1},{slug:"fremd",vi:0,qty:1}]),[{slug:"alt",vi:0,qty:2}]);
// 3D-Modell: gültig, ungültig, Aufteilen in 16-Bit-Blöcke
const b64=a=>Buffer.from(a.buffer).toString("base64");
const quad={version:1,parts:[{p:b64(new Float32Array([0,0,0,1,0,0,1,1,0,0,1,0])),n:b64(new Float32Array([0,0,1,0,0,1,0,0,1,0,0,1])),i:b64(new Uint16Array([0,1,2,0,2,3])),count:6,color:[1,0,0],metal:1}]};
const m=parseModel(quad);assert.strictEqual(m[0].k,4);assert.strictEqual(m[0].c[0].i.length,6);
let lo=1e9,hi=-1e9;const v=m[0].c[0].v;for(let k=1;k<v.length;k+=8){lo=Math.min(lo,v[k]);hi=Math.max(hi,v[k])}
assert.ok(Math.abs(lo-(VIAL_H-1.4)/2)<1e-5&&Math.abs(hi-(VIAL_H+1.4)/2)<1e-5,"mittig, 1,4 breit");
const bad=[{},{version:2,parts:quad.parts},{version:1,parts:[]},{version:1,parts:[{...quad.parts[0],count:7}]},
  {version:1,parts:[{...quad.parts[0],i:b64(new Uint16Array([0,1,9]))}]},{version:1,parts:[{...quad.parts[0],p:"AAAA"}]},
  {version:1,parts:[{...quad.parts[0],p:b64(new Float32Array([0,0,0,NaN,0,0,1,1,0,0,1,0]))}]}];
for(const j of bad)assert.throws(()=>parseModel(j));
const N=70000,p=new Float32Array(N*3),n=new Float32Array(N*3),ix=new Uint32Array((N-2)*3);
for(let k=0;k<N;k++){p[k*3]=k%100;p[k*3+1]=Math.floor(k/100);n[k*3+2]=1}for(let k=0;k<N-2;k++){ix[k*3]=k;ix[k*3+1]=k+1;ix[k*3+2]=k+2}
const big=parseModel({version:1,parts:[{p:b64(p),n:b64(n),i:b64(ix),index32:true,count:ix.length}]})[0].c;
assert.ok(big.length===2&&big.every(c=>c.v.length/8<=65536&&c.i instanceof Uint16Array));
assert.strictEqual(big.reduce((a,c)=>a+c.i.length,0),ix.length);
console.log("OK");
"""


@pytest.mark.skipif(not NODE, reason="node nicht installiert")
def test_frontend_functions_node(tmp_path):
    js = _script()
    parts = [_grab(js, "const esc="), _grab(js, "const safeUrl="), _grab(js, "const clamp="), _grab(js, "const modelUrlOk="),
             _grab(js, "function b64buf("), _grab(js, "function parseModel("), _grab(js, "function splitMesh("),
             _grab(js, "const okVariants="), _grab(js, "function newProduct(")]
    clean = re.search(r"^  clean\(list\).*?\n(?=  load\()", js, re.S | re.M).group(0)
    code = "\n".join(parts) + "const Cart={\n" + clean + "};\n" + NODE_TEST
    f = tmp_path / "t.js"
    f.write_text(re.sub(r"@@[A-Z_]+@@", "", code), encoding="utf-8")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr


# ---------------------------------------------------------------- echte Seite im Headless-Browser
CDP = r"""
const {spawn}=require("child_process"),fs=require("fs"),path=require("path");
const [,,chrome,dir,url]=process.argv,sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ch=spawn(chrome,["--headless=new","--no-sandbox","--remote-debugging-port=0","--user-data-dir="+dir,"--use-angle=swiftshader",
  "--enable-unsafe-swiftshader","--window-size=1280,900","about:blank"],{stdio:"ignore"});
const done=c=>{try{ch.kill()}catch(e){}process.exit(c)};setTimeout(()=>{console.error("Zeitüberschreitung");done(2)},90000);
(async()=>{let port;for(let i=0;i<200&&!port;i++){try{port=fs.readFileSync(path.join(dir,"DevToolsActivePort"),"utf8").split("\n")[0]}catch(e){}await sleep(100)}
  let tgt;for(let i=0;i<100&&!tgt;i++){try{tgt=(await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(x=>x.type==="page")}catch(e){}await sleep(100)}
  const ws=new WebSocket(tgt.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);let id=0;const pend={},errs=[],warn=[];
  ws.onmessage=m=>{const j=JSON.parse(m.data);if(j.id&&pend[j.id]){pend[j.id](j);delete pend[j.id]}
    else if(j.method==="Runtime.exceptionThrown")errs.push(j.params.exceptionDetails.exception?.description||j.params.exceptionDetails.text);
    else if(j.method==="Runtime.consoleAPICalled"&&j.params.type==="warning")warn.push(j.params.args.map(a=>a.value).join(" "))};
  const send=(method,params={})=>new Promise(r=>{const i=++id;pend[i]=r;ws.send(JSON.stringify({id:i,method,params}))});
  const ev=async e=>(await send("Runtime.evaluate",{expression:e,awaitPromise:true,returnByValue:true})).result.result.value;
  const until=async e=>{for(let i=0;i<150;i++){if(await ev(e))return true;await sleep(200)}return false};
  await send("Runtime.enable");await send("Page.enable");
  await send("Page.navigate",{url:url+"/de/"});await until("document.readyState==='complete'");
  await ev("localStorage.setItem('gp_cart',JSON.stringify([{slug:'omega-alt',vi:0,qty:1},{slug:'beta',vi:0,qty:2}]));1");
  await send("Page.navigate",{url:url+"/de/"});
  const out={};out.ready=await until("!!document.querySelector('.card[data-slug=x-neu]')");
  Object.assign(out,await ev(`(()=>{const c=document.querySelector('.card[data-slug=x-neu]');return{cards:[...document.querySelectorAll('.card')].map(c=>c.dataset.slug),
    h3:c&&c.querySelector('h3').textContent,injected:!!document.querySelector('#pwn'),img:c&&c.querySelector('img.fb').getAttribute('src'),
    gl:!document.documentElement.classList.contains('no-gl')}})()`));
  await send("Page.navigate",{url:url+"/de/x-neu/"});
  await until("document.querySelector('#cartN').textContent!=='0'");
  out.detail=await until("document.documentElement.classList.contains('detail-open')&&document.querySelector('#dName').textContent.length>0");
  Object.assign(out,await ev(`({dName:document.querySelector('#dName').textContent,spec:document.querySelector('#dSpec').textContent,
    focus:document.querySelector('#rList').textContent,cartN:document.querySelector('#cartN').textContent,injected2:!!document.querySelector('#pwn'),cert:document.querySelector('#dCert').getAttribute('href')})`));
  await sleep(1500);out.errs=errs;out.warn=warn;console.log(JSON.stringify(out));ws.close();done(0)})().catch(e=>{console.error(e);done(1)});
"""

EVIL = 'A <b id="pwn">B</b> & "C"'


# nur lokal: in der Deploy-Pipeline (CI) kann headless Chrome ohne GPU wackeln und würde Deploys blockieren
@pytest.mark.skipif(bool(os.environ.get("CI")), reason="Browser-Test nur lokal, nicht in CI")
@pytest.mark.skipif(not NODE or not _chrome(), reason="node oder Chrome nicht installiert")
def test_frontend_in_browser(tmp_path):
    from werkzeug.serving import make_server
    site = harness.fixture_copy(tmp_path)
    (site / "models").mkdir()
    (site / "models" / "kaputt.json").write_text('{"version":1,"parts":[{"p":"AAAA"}]}', encoding="utf-8")
    data = json.loads((site / "products.json").read_text(encoding="utf-8"))
    data["products"].append({"slug": "x-neu", "name": EVIL, "cls": "Test<i>", "variants": [{"label": "5 <mg>", "price": 12.5}],
                             "purity": "≥99 %", "accent": "#22AA88", "tags": ["single"], "model": "/models/kaputt.json",
                             "image": "javascript:alert(1)", "certificate": "javascript:alert(2)",
                             "research": {"short": "K", "intro": "I", "focus": ['<b id="pwn">f</b>'], "stage": "S"}})
    (site / "products.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    # fremdes Backend nachstellen: die ausgelieferte Seite kennt "x-neu" noch nicht, dafür das entfernte "omega-alt"
    orig = app.shop_site.product_rows
    app.shop_site.product_rows = lambda prods: orig([p for p in prods if p["slug"] != "x-neu"] + [
        {"slug": "omega-alt", "name": "Omega", "cls": "Alt", "accent": "#888888", "variants": [{"label": "5 mg", "price": 5}]}])
    srv = make_server("127.0.0.1", 0, app.app, threaded=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        f = tmp_path / "cdp.js"
        f.write_text(CDP, encoding="utf-8")
        r = subprocess.run([NODE, str(f), _chrome(), str(tmp_path / "chrome"), f"http://127.0.0.1:{srv.server_port}"],
                           capture_output=True, text=True, timeout=150, encoding="utf-8")
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ready"] and out["detail"], out
    assert out["cards"] == ["alpha", "beta", "test-water", "x-neu"]   # neu ergänzt, entferntes ausgeblendet
    assert out["h3"] == EVIL and out["dName"] == EVIL                # als Text, nicht als HTML
    assert not out["injected"] and not out["injected2"]
    assert "5 <mg>" in out["spec"] and "Test<i>" in out["spec"] and '<b id="pwn">f</b>' in out["focus"]
    assert out["img"] == "" and out["cert"] != "javascript:alert(2)"   # unsichere Adressen verworfen
    assert out["cartN"] == "2"                                       # entferntes Produkt nicht mehr im Warenkorb
    assert not out["errs"], out["errs"]
    if out["gl"]:  # ohne WebGL wird kein Modell geladen
        assert any("kaputt.json" in w for w in out["warn"]), out["warn"]  # kaputtes Modell -> Standard-Vial mit Hinweis

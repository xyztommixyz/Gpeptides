const P = [
 {slug:"glow-stack",name:"GLOW Stack",short:"GLOW",cls:"Multi-Peptid-Set",v:[["70 mg",84.9]],pur:"≥98 %",cap:"#F5B700",tags:["best","blend"]},
 {slug:"glp-3",name:"GLP-3",cls:"GLP-1 / GIP / Glukagon",v:[["10 mg",49.9],["20 mg",92.9]],pur:"≥98 %",cap:"#7B5CFF",tags:["best","single"]},
 {slug:"bpc-157",name:"BPC-157",cls:"Pentadecapeptid",v:[["5 mg",32.9]],pur:"≥98 %",cap:"#3A86FF",tags:["best","single"]},
 {slug:"ghk-cu",name:"GHK-Cu",cls:"Kupferpeptid",v:[["50 mg",27.9],["100 mg",45.9]],pur:"≥98 %",cap:"#C8743A",tags:["best","single"]},
 {slug:"tesamorelin",name:"Tesamorelin",cls:"GHRH-Analogon",v:[["10 mg",47.9]],pur:"≥98 %",cap:"#00B8A9",tags:["single"]},
 {slug:"cjc-1295-ipamorelin",name:"CJC-1295 + Ipamorelin",short:"CJC + IPA",cls:"GHRH / GHRP Blend",v:[["10 mg",55.9]],pur:"≥98 %",cap:"#FF6B35",tags:["blend"]},
 {slug:"ipamorelin",name:"Ipamorelin",cls:"GHRP",v:[["10 mg",33.9]],pur:"≥99 %",cap:"#FF8FB1",tags:["single"],st:"pre"},
 {slug:"cjc-1295-no-dac",name:"CJC-1295 (No DAC)",short:"CJC-1295",cls:"GHRH-Analogon",v:[["10 mg",53.9]],pur:"≥98 %",cap:"#E63946",tags:["single"],st:"oos"},
 {slug:"bpc-157-tb500",name:"BPC-157 + TB500",short:"BPC + TB",cls:"Peptidfragment-Blend",v:[["10 mg",60.9]],pur:"≥98 %",cap:"#4CC9F0",tags:["blend"]},
 {slug:"tb-500",name:"TB-500",cls:"Thymosin β4",v:[["5 mg",32.9]],pur:"≥98 %",cap:"#8AC926",tags:["single"]},
 {slug:"mt2",name:"MT2",cls:"Melanotan II / Melanocortin",v:[["10 mg",29.9]],pur:"≥98 %",cap:"#8D5B4C",tags:["single"]},
 {slug:"mt1",name:"MT1",cls:"Melanotan I / Afamelanotid",v:[["10 mg",30.9]],pur:"≥98 %",cap:"#B49A8C",tags:["single"]},
 {slug:"mots-c",name:"MOTS-c",cls:"Mitochondriales Peptid",v:[["10 mg",33.9],["40 mg",109.9]],pur:"≥97 %",cap:"#FF006E",tags:["single"]},
 {slug:"klow",name:"KLOW",cls:"Peptid-Blend",v:[["80 mg",95.9]],pur:"≥98 %",cap:"#FFD23F",tags:["blend"]},
 {slug:"glp-3-ghk-cu",name:"GLP-3 + GHK-Cu",short:"GLP-3 + GHK",cls:"Forschungs-Bundle · 2 Vials",v:[["Bundle",67.9],["Bundle XL",119.9]],pur:"≥98 %",cap:"#9B5DE5",tags:["bundle"]},
 {slug:"semax-selank",name:"Semax + Selank",short:"SEMAX + SELANK",cls:"Peptid-Bundle · 2 Vials",v:[["Bundle",55.9]],pur:"≥98 %",cap:"#F15BB5",tags:["bundle"]},
 {slug:"glutathione",name:"Glutathion",cls:"Tripeptid",v:[["600 mg",30.9]],pur:"≥98 %",cap:"#90A4AE",tags:["single"],st:"oos"},
 {slug:"kpv",name:"KPV",cls:"α-MSH-Fragment",v:[["10 mg",32.9]],pur:"≥98 %",cap:"#06D6A0",tags:["single"]},
 {slug:"semax",name:"Semax",cls:"ACTH(4-10)-Analogon",v:[["10 mg",29.9]],pur:"≥98 %",cap:"#118AB2",tags:["single"]},
 {slug:"selank",name:"Selank",cls:"Tuftsin-Analogon",v:[["10 mg",29.9]],pur:"≥98 %",cap:"#EF476F",tags:["single"]},
 {slug:"cagrilintide",name:"Cagrilintide",cls:"Amylin-Analogon",v:[["10 mg",64.9]],pur:"≥98 %",cap:"#5E60CE",tags:["single"]},
 {slug:"bac-water",name:"Bac-Water",cls:"Lösungsmittel",v:[["10 ml",9.9]],pur:"-",cap:"#B0BEC5",tags:["acc"],liquid:true},
];
// Zusatzdaten (werden bei Server-Betrieb aus /products.json aktualisiert)
const EXTRA={"glow-stack":[0,"0f855bf9"],"glp-3":[1,"fd0fc3b9"],"tesamorelin":[2,"b6326620"],"cjc-1295-ipamorelin":[3,"9c1fa44e"],"ipamorelin":[4,"f55a32eb"],"cjc-1295-no-dac":[5,"de60654f"],"bpc-157-tb500":[6,"de19b238"],"bpc-157":[7,"3d9ab6b2"],"tb-500":[8,"e1661e37"],"mt2":[10,"c2a55601"],"mt1":[11,"6215a037"],"mots-c":[12,"6cf346b8"],"ghk-cu":[13,"11806ee0"],"glp-3-ghk-cu":[14,"6c4768d2"],"semax-selank":[15,"3388a51a"],"klow":[16,"24cee3c7"],"glutathione":[17,"aad16a8e"],"kpv":[18,"4c534516"],"semax":[19,"94692c05"],"selank":[20,"8de5a0a1"],"bac-water":[100,"a109d860"],"cagrilintide":[102,"c673fb9b"]};
const BUNDLES={"glp-3-ghk-cu":["glp-3","ghk-cu"],"semax-selank":["semax","selank"]};
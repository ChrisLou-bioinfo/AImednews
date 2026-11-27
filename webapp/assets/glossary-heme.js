/* 血液肿瘤术语悬浮解释（吸收 onco.cc 的 "Plain English first + glossary hover" 设计）
 * 原则：一句话人话解释；只陈述定义与共识，不替读者下结论；标注类别。
 * 数据为静态词条，不依赖网络。*/
window.HEME_GLOSSARY = {
  "ICANS": {cat:"毒性", aka:["ICANS","neurotoxicity"], tldr:"免疫效应细胞相关神经毒性综合征。可表现为语言、注意力、书写或意识改变；严重时可抽搐。分级需结合基线与其他病因，不能用细胞因子曲线替代临床评估。"},
  "CRS": {cat:"毒性", aka:["CRS","cytokine release syndrome"], tldr:"细胞因子释放综合征。免疫治疗后出现的发热、低血压、缺氧等系统性炎症反应，按严重度分级处理（液体、升压药、IL-6/IL-6R 阻断、糖皮质激素）。"},
  "MRD": {cat:"疗效终点", aka:["MRD","minimal residual disease","微小残留"], tldr:"微小残留病。用流式、PCR 或测序在形态学缓解后检出残留肿瘤细胞。MRD 阴性常被用作缓解深度指标，但检测方法与灵敏度不同，结果不能直接互换。"},
  "CAR-T": {cat:"细胞治疗", aka:["CAR-T","CAR T","chimeric antigen receptor","嵌合抗原受体"], tldr:"把识别肿瘤抗原的单链抗体片段与 T 细胞信号域融合，经病毒或非病毒载体导入自体/异体 T 细胞。疗效与抗原表达、细胞持久性、既往治疗线数相关；同时需管理 CRS/ICANS。"},
  "双特异性抗体": {cat:"免疫治疗", aka:["双抗","bispecific","bispecific antibody","BiTE","T-cell engager"], tldr:"同时结合两个靶点（常见为肿瘤抗原与 CD3）的抗体构建体。作用依赖 T 细胞重定向，通常不需体外扩增；半衰期与是否含 Fc 结构相关。"},
  "ADC": {cat:"免疫治疗", aka:["ADC","antibody-drug conjugate","抗体偶联药物"], tldr:"抗体-药物偶联物。通过连接子把细胞毒载荷偶联到抗体上。疗效取决于抗原密度与内吞、连接子稳定性、载荷外排与旁观者效应；毒性常包括骨髓抑制与周围神经病变。"},
  "B-ALL": {cat:"疾病", aka:["B-ALL","B cell acute lymphoblastic leukemia","急性淋巴细胞白血病"], tldr:"B 细胞急性淋巴细胞白血病。儿童最常见急性白血病；危险度分层依据年龄、白细胞数、遗传学（如 BCR-ABL1、KMT2A 重排）与 MRD 反应。"},
  "AML": {cat:"疾病", aka:["AML","acute myeloid leukemia","急性髓系白血病"], tldr:"急性髓系白血病。治疗决策依赖遗传学与分子分型（如 FLT3、NPM1、IDH1/2、KMT2A 重排）及是否适合强化疗/移植。"},
  "KMT2A": {cat:"分子分型", aka:["KMT2A","MLL","KMT2A rearrangement","KMT2A 重排"], tldr:"组蛋白 H3K4 甲基转移酶基因。KMT2A 重排（尤其婴儿与儿童 AML/ALL）属高危亚型，常与 menin 依赖的转录程序相关，是 menin 抑制剂的依据之一。"},
  "menin": {cat:"靶点", aka:["menin","MEN1","menin 抑制剂"], tldr:"MEN1 基因产物，与 KMT2A 融合蛋白相互作用并维持其致癌转录程序。menin 抑制剂通过阻断该相互作用诱导分化，适用于 KMT2A 重排/NPM1 突变等亚型。"},
  "FLT3": {cat:"靶点", aka:["FLT3","FLT3-ITD","FLT3 抑制剂"], tldr:"受体酪氨酸激酶。FLT3-ITD 等突变见于部分 AML，与复发风险相关；FLT3 抑制剂用于相应亚型，但需注意骨髓抑制与耐药。"},
  "BCL-2": {cat:"靶点", aka:["BCL-2","venetoclax","维奈克拉"], tldr:"抗凋亡蛋白。BCL-2 抑制剂（如 venetoclax）在 CLL 与 AML（联合去甲基化药物）中应用；主要毒性为骨髓抑制与肿瘤溶解风险。"},
  "BTK": {cat:"靶点", aka:["BTK","BTK 抑制剂","ibrutinib","acalabrutinib","zanubrutinib"], tldr:"布鲁顿酪氨酸激酶，B 细胞受体信号的关键节点。BTK 抑制剂用于 CLL/套细胞淋巴瘤等；共价与非共价抑制剂对耐药突变的敏感性不同。"},
  "HSCT": {cat:"治疗方式", aka:["HSCT","造血干细胞移植","allo-HSCT","移植"], tldr:"造血干细胞移植。高危血液肿瘤的巩固/根治手段之一；适应证取决于疾病风险、缓解状态、供者与合并症，移植相关死亡率与 GVHD 是主要限制。"},
  "GVHD": {cat:"并发症", aka:["GVHD","移植物抗宿主病"], tldr:"移植物抗宿主病。异基因移植后供者免疫细胞攻击宿主组织，分急性与慢性；预防与治疗以免疫抑制为主，需权衡感染与复发风险。"},
  "blinatumomab": {cat:"药物", aka:["blinatumomab","贝林妥欧单抗"], tldr:"CD19×CD3 双特异性 T 细胞衔接分子。用于 B-ALL（含 MRD 阳性与复发/难治）；需持续输注，注意 CRS、神经毒性。"},
  "inotuzumab": {cat:"药物", aka:["inotuzumab","inotuzumab ozogamicin","奥加伊妥珠单抗"], tldr:"CD22 抗体-药物偶联物，用于复发/难治 B-ALL。与移植前的肝窦阻塞综合征（VOD/SOS）风险相关。"},
  "venetoclax": {cat:"药物", aka:["venetoclax","维奈克拉"], tldr:"BCL-2 选择性抑制剂。在 AML 常与去甲基化药物或低强度方案联合；需监测肿瘤溶解综合征与血细胞减少。"},
  "revumenib": {cat:"药物", aka:["revumenib","ziftomenib"], tldr:"menin 抑制剂类。用于 KMT2A 重排等亚型，诱导白血病细胞分化；注意分化综合征与 QT 间期。"},
  "CD19": {cat:"靶点", aka:["CD19"], tldr:"B 细胞表面标志，B 系肿瘤与 CAR-T/双抗的主要靶点之一。正常 B 细胞亦表达，治疗后可出现低丙种球蛋白血症，需替代治疗。"},
  "CD22": {cat:"靶点", aka:["CD22"], tldr:"B 细胞表面抑制性受体，常与 CD19/CD20 并列作为 B-ALL、B 细胞淋巴瘤的治疗靶点（ADC、CAR-T、双抗）。"},
  "CD30": {cat:"靶点", aka:["CD30","TNFRSF8"], tldr:"肿瘤坏死因子受体超家族成员，霍奇金淋巴瘤与间变性大细胞淋巴瘤的标志性抗原，是 CD30 ADC 的靶点。"},
  "BCMA": {cat:"靶点", aka:["BCMA","TNFRSF17"], tldr:"B 细胞成熟抗原，浆细胞与多发性骨髓瘤细胞高表达，是 CAR-T 与双抗的靶点（如 cilta-cel、teclistamab）。"},
  "GPRC5D": {cat:"靶点", aka:["GPRC5D"], tldr:"G 蛋白偶联受体家族 C 组 5 成员 D，骨髓瘤细胞高表达，作为 BCMA 之外的 CAR-T/双抗靶点；正常组织表达带来特定毒性（如指甲、皮肤）。"},
  "EFS": {cat:"终点", aka:["EFS","event-free survival","无事件生存"], tldr:"无事件生存期。事件定义（复发、死亡、第二肿瘤等）各研究不同，跨试验比较需核对事件定义与统计假设。"},
  "OS": {cat:"终点", aka:["OS","overall survival","总生存"], tldr:"总生存期。终点较明确但需更长时间与更大样本；获益需看是否伴随生活质量与毒性可接受。"},
  "HR": {cat:"统计", aka:["HR","hazard ratio","风险比"], tldr:"风险比。比较两组事件发生速率的相对值；须与 95% 置信区间、样本量与随访时间一起解读，HR<1 不等于个体必然获益。"}
};

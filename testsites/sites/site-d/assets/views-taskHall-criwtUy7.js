export function renderTaskHall(t){const levels=[1,2,3].map(n=>({name:'VIP '+n,orders:20+n*10}));
return {title:t['nav.tasks'],levels,locked:t['task.locked'],cta:t['task.unlock'],grab:t['task.grab']}}
export const ORDER_STATES=['pending','frozen','completed'];export const RECHARGE_PRESETS=[500,1500,5000];
function taskHallH0(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*1,amt:r.amount+0}));return t?n.filter(r=>r.lv>=0):n}
function taskHallH1(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*2,amt:r.amount+50}));return t?n.filter(r=>r.lv>=1):n}
function taskHallH2(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*3,amt:r.amount+100}));return t?n.filter(r=>r.lv>=2):n}
function taskHallH3(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*4,amt:r.amount+150}));return t?n.filter(r=>r.lv>=3):n}
function taskHallH4(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*5,amt:r.amount+200}));return t?n.filter(r=>r.lv>=4):n}
function taskHallH5(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*6,amt:r.amount+250}));return t?n.filter(r=>r.lv>=5):n}
function taskHallH6(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*7,amt:r.amount+300}));return t?n.filter(r=>r.lv>=6):n}
function taskHallH7(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*8,amt:r.amount+350}));return t?n.filter(r=>r.lv>=7):n}
function taskHallH8(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*9,amt:r.amount+400}));return t?n.filter(r=>r.lv>=8):n}
function taskHallH9(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*10,amt:r.amount+450}));return t?n.filter(r=>r.lv>=9):n}
function taskHallH10(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*11,amt:r.amount+500}));return t?n.filter(r=>r.lv>=10):n}
function taskHallH11(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*12,amt:r.amount+550}));return t?n.filter(r=>r.lv>=11):n}
function taskHallH12(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*13,amt:r.amount+600}));return t?n.filter(r=>r.lv>=12):n}
function taskHallH13(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*14,amt:r.amount+650}));return t?n.filter(r=>r.lv>=13):n}
function taskHallH14(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*15,amt:r.amount+700}));return t?n.filter(r=>r.lv>=14):n}
function taskHallH15(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*16,amt:r.amount+750}));return t?n.filter(r=>r.lv>=15):n}
function taskHallH16(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*17,amt:r.amount+800}));return t?n.filter(r=>r.lv>=16):n}
function taskHallH17(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*18,amt:r.amount+850}));return t?n.filter(r=>r.lv>=17):n}
function taskHallH18(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*19,amt:r.amount+900}));return t?n.filter(r=>r.lv>=18):n}
function taskHallH19(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*20,amt:r.amount+950}));return t?n.filter(r=>r.lv>=19):n}
function taskHallH20(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*21,amt:r.amount+1000}));return t?n.filter(r=>r.lv>=20):n}
function taskHallH21(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*22,amt:r.amount+1050}));return t?n.filter(r=>r.lv>=21):n}
function taskHallH22(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*23,amt:r.amount+1100}));return t?n.filter(r=>r.lv>=22):n}
function taskHallH23(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*24,amt:r.amount+1150}));return t?n.filter(r=>r.lv>=23):n}
function taskHallH24(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*25,amt:r.amount+1200}));return t?n.filter(r=>r.lv>=24):n}
function taskHallH25(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*26,amt:r.amount+1250}));return t?n.filter(r=>r.lv>=25):n}
function taskHallH26(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*27,amt:r.amount+1300}));return t?n.filter(r=>r.lv>=26):n}
function taskHallH27(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*28,amt:r.amount+1350}));return t?n.filter(r=>r.lv>=27):n}
function taskHallH28(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*29,amt:r.amount+1400}));return t?n.filter(r=>r.lv>=28):n}
function taskHallH29(e,t){const n=(e||[]).map(r=>({id:r.id,lv:r.level*30,amt:r.amount+1450}));return t?n.filter(r=>r.lv>=29):n}
export const taskHallHelpers=[taskHallH0,taskHallH1,taskHallH2,taskHallH3,taskHallH4,taskHallH5,taskHallH6,taskHallH7,taskHallH8,taskHallH9,taskHallH10,taskHallH11,taskHallH12,taskHallH13,taskHallH14,taskHallH15,taskHallH16,taskHallH17,taskHallH18,taskHallH19,taskHallH20,taskHallH21,taskHallH22,taskHallH23,taskHallH24,taskHallH25,taskHallH26,taskHallH27,taskHallH28,taskHallH29];

'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const scripts = path.join(__dirname, '../src/panorama/scripts');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
class Panel {
  constructor(type, parent, id, classes = '') {
    this.paneltype = type; this.parent = parent; this.id = id; this.children = [];
    this.classes = new Set(classes.split(' ').filter(Boolean)); this.style = {}; this.attrs = {}; this.events = {}; this.vars = {}; this.text = ''; this.visible = true; this.alive = true;
    if (parent) parent.children.push(this);
  }
  GetParent() { return this.parent; } IsValid() { return this.alive; } Children() { return this.children; }
  GetChild(i) { return this.children[i]; } AddClass(c) { this.classes.add(c); } BHasClass(c) { return this.classes.has(c); }
  SetHasClass(c,v) { v ? this.classes.add(c) : this.classes.delete(c); }
  FindChildTraverse(id) { for (const c of this.children) { if(c.id===id)return c; const found=c.FindChildTraverse(id);if(found)return found; } return null; }
  GetAttributeString(k,d) { return this.attrs[k] ?? d; } SetAttributeString(k,v) { this.attrs[k]=v; }
  SetPanelEvent(k,v) { this.events[k]=v; } SetFocus() {} SelectAll() {}
  SetDialogVariable(k,v) { this.vars[k]=String(v); }
  MoveChildAfter(child, after) { this.children=this.children.filter(p=>p!==child); this.children.splice(this.children.indexOf(after)+1,0,child); }
  RemoveAndDeleteChildren() { this.children=[]; } SetImage(url) { this.image=url; }
  DeleteAsync() { this.parent.children=this.parent.children.filter(p=>p!==this); this.alive=false; }
}
// What a label shows once Panorama fills {s:...} from the label's own dialog variables.
const shown = label => label.text.replace(/\{s:(\w+)\}/g, (m, k) => label.vars[k] ?? m);
function context(host, config = {}, clock = {now:1000}, options = {}) {
  const jobs=[], events=[], bus=options.bus||{handlers:[]}, unregistered=[];
  const dollar={GetContextPanel:()=>host,CreatePanel:(...a)=>new Panel(...a),Msg:()=>{},
    Schedule:(delay,fn)=>{jobs.push({delay,fn});return jobs.length;},CancelScheduled:()=>{},
    RegisterForUnhandledEvent:(name,fn)=>{bus.handlers.push(fn);return bus.handlers.length;},
    UnregisterForUnhandledEvent:(name,handle)=>{unregistered.push(handle);bus.handlers[handle-1]=()=>{};},
    DispatchEvent:(...args)=>{events.push(args);if(args[0]==='UIPopupButtonClicked'){assert.equal(args.length,2);assert.equal(typeof args[1],'string');}
      if(args[0]==='ClientUI_FireOutput')bus.handlers.slice().forEach(fn=>fn(args[1]));}
  };
  const boot={settings:config,token:'local-test',version:'0.2.4',...(options.boot||{})};
  const ctx=vm.createContext({$:dollar,SwitchboardBoot:boot,console,Date:class extends Date { static now(){return clock.now;} }});
  vm.runInContext(fs.readFileSync(path.join(scripts,'switchboard_shared.vts'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(scripts,'switchboard_runtime.vts'),'utf8'),ctx);
  jobs.find(j=>j.delay===.1).fn();
  return {ctx,jobs,events,bus,unregistered,handlers:bus.handlers,model:ctx.SwitchboardModel,
    send(config,revision=1){bus.handlers.slice().forEach(fn=>fn(JSON.stringify({switchboard:'switchboard.chat.v1',source:'test',kind:'changed',revision,settings:config})));},
    tick(){jobs.find(j=>j.delay===.2)?.fn();},
    last(delay){return jobs.filter(j=>j.delay===delay).at(-1);}};
}
function chat() {
  const root=new Panel('Panel',null,'root'),host=new Panel('CitadelChat',root,'Chat','ChatDisabled');
  const area=new Panel('Panel',host,'ChatLinesArea'),wrapper=new Panel('Panel',area,'wrapper');
  const messages=new Panel('Panel',wrapper,'ChatMessages'),controls=new Panel('Panel',host,'ChatControls');
  new Panel('TextEntry',controls,'ChatInput');
  function row(kind,text,classes='',player='Player'){
    const r=new Panel('Panel',messages,'','ChatMessage '+classes),body=new Panel('Panel',r,'body','MessageBody');
    const image=new Panel('Panel',r,'SenderImage');
    const source=new Panel('Panel',body,'MessageSource'),name=new Panel('Label',source,'name','SenderName');name.text=player;
    new Panel('Label',source,'','SBColon').text=':';
    const contents=new Panel('Panel',body,'MessageContents',kind),label=new Panel('Label',contents,'');label.text=text;
    return {row:r,label,name,image,contents};
  }
  return {host,messages,controls,row};
}
function popup() {
  const root=new Panel('Panel',null,'root'),host=new Panel('PopupCustomLayout',root,'SwitchboardPopup','SBPopup');
  for(const id of ['SBClose','SBDone','SBBackdrop','SBVersion','SBPresets','SBPresetNote','SBTabs','SBControls','SBPreview','SBPreviewTeam','SBPreviewPing','SBPreviewObjective','SBStatus'])new Panel(id==='SBVersion'||id==='SBStatus'||id==='SBPresetNote'?'Label':'Panel',host,id);
  return host;
}
function displayed(line) {
  const ours=line.row.FindChildTraverse('SBSenderName');
  if(ours&&!ours.BHasClass('SBNameUnused')){assert(line.name.BHasClass('SBNativeName'));return shown(ours);}
  assert(!line.name.BHasClass('SBNativeName'));return line.name.text;
}
function roster(root,player,hero){
  const p=new Panel('CitadelHudTopBarPlayer',root,'player'),info=new Panel('Panel',p,'PlayerNameNWContainer');
  const a=new Panel('Label',info,'','PlayerName');a.text=player;const b=new Panel('Label',info,'','HeroName');b.text=hero;return b;
}
test('native expiry, chat input and mute state survive styling and filtering',()=>{
  const c=chat(),expired=c.row('Text','message','Expired'),ping=c.row('Ping','On my way!'),objective=c.row('Ping','Attack the Walker');
  const r=context(c.host);r.tick();
  assert(c.host.BHasClass('ChatDisabled'));assert(expired.row.BHasClass('Expired'));
  assert.equal(expired.row.style.opacity,undefined);assert.deepEqual(c.controls.FindChildTraverse('ChatInput').events,{});
  r.send({...r.model.defaults,showPings:false,showCallouts:false,showObjectives:true});r.tick();
  assert(ping.row.BHasClass('SBFiltered'));assert(!objective.row.BHasClass('SBFiltered'));assert(!expired.row.BHasClass('SBFiltered'));
  r.send({...r.model.defaults,mode:'native'},2);r.tick();
  assert(!c.host.BHasClass('SBStyled'));assert.equal(c.host.style.width,'');assert.equal(expired.label.style.fontSize,'');
  assert(expired.row.BHasClass('Expired'));assert.equal(expired.row.style.opacity,undefined);
});
test('cross-context settings use only the namespaced preference protocol',()=>{
  const c=chat(),r=context(c.host);const before=JSON.stringify(r.ctx.SwitchboardModel.defaults);
  for(const payload of ['not JSON','{"umm":1}',JSON.stringify({switchboard:'wrong',kind:'changed'}),'x'.repeat(20000)])r.handlers.forEach(fn=>fn(payload));
  assert.equal(JSON.stringify(r.ctx.SwitchboardModel.defaults),before);
  r.ctx.SwitchboardOpen();const event=r.events.find(e=>e[0]==='UIShowCustomLayoutPopup');
  assert.deepEqual(event,['UIShowCustomLayoutPopup','SwitchboardPopup','s2r://panorama/layout/switchboard_panel.xml']);
});
test('preset controls save preference-only payloads and use the native close contract',()=>{
  const host=popup(),r=context(host);host.FindChildTraverse('SBPreset_rivals').events.onactivate();
  assert.equal(host.FindChildTraverse('SBVersion').text,'0.2.4');
  r.last(.5).fn();const sink=host.FindChildTraverse('SBPreferenceSink');
  const url=new URL(sink.image);assert.equal(url.hostname,'127.0.0.1');
  const config=JSON.parse(url.searchParams.get('settings'));assert.equal(config.preset,'rivals');assert.equal(config.bold,true);
  assert(!url.toString().includes('message_text'));host.FindChildTraverse('SBClose').events.onactivate();
  assert.deepEqual(r.events.at(-1),['UIPopupButtonClicked','']);
});
test('closing the popup straight after a change flushes the save at once',()=>{
  const host=popup(),r=context(host);host.FindChildTraverse('SBPreset_league').events.onactivate();
  assert.equal(host.FindChildTraverse('SBPreferenceSink'),null);
  host.FindChildTraverse('SBDone').events.onactivate();
  const sink=host.FindChildTraverse('SBPreferenceSink');assert(sink,'save must happen before the popup closes');
  assert.equal(JSON.parse(new URL(sink.image).searchParams.get('settings')).preset,'league');
  const saves=r.events.filter(e=>e[0]==='ClientUI_FireOutput'&&e[1].includes('"kind":"saved"'));assert.equal(saves.length,1);
  r.last(.5).fn();assert.equal(r.events.filter(e=>e[0]==='ClientUI_FireOutput'&&e[1].includes('"kind":"saved"')).length,1);
});
test('a long-lived chat context saves popup changes once, even after the popup is gone',()=>{
  const bus={handlers:[]},c=chat(),chatCtx=context(c.host,{},{now:1000},{bus});
  const footerRoot=new Panel('Panel',null,'droot'),footer=new Panel('Panel',footerRoot,'Footer'),footerCtx=context(footer,{},{now:1000},{bus});
  const host=popup(),p=context(host,{},{now:1000},{bus});
  host.FindChildTraverse('SBPreset_overwatch').events.onactivate();
  host.FindChildTraverse('SBClose').events.onactivate();host.alive=false;
  assert.equal(host.FindChildTraverse('SBPreferenceSink'),null,'popup leaves saving to the chat context');
  assert.equal(p.last(.5),undefined);
  chatCtx.last(.3).fn();footerCtx.last(.4).fn();
  const sink=c.host.FindChildTraverse('SBPreferenceSink');assert(sink);
  assert.equal(JSON.parse(new URL(sink.image).searchParams.get('settings')).preset,'overwatch');
  assert.equal(footer.FindChildTraverse('SBPreferenceSink'),null,'second saver is cancelled by the saved notice');
  p.jobs.find(j=>j.delay===1)?.fn();assert(p.unregistered.length===1,'popup handler is removed once its panel is gone');
});
test('themes reject executable or malformed settings, clamp dimensions and keep filters on preset changes',()=>{
  const r=context(chat().host),M=r.model;
  assert.throws(()=>M.decode('{"font":"url(https://example.com)"}'));
  assert.throws(()=>M.normalize({fontSize:'22px'}));assert.throws(()=>M.normalize({showPings:'false'}));
  assert.throws(()=>M.normalize({version:2}));assert.equal(M.normalize({width:9000}).width,820);
  assert.throws(()=>M.normalize({mode:'loud'}),/Unrecognised mode/);
  const base=M.normalize({showText:false,showPings:false});assert.equal(M.preset('league',base).showText,false);
  const encoded=M.encode(M.preset('overwatch'));assert.equal(M.decode(encoded).preset,'overwatch');
});
test('theme import merges appearance and filters only and explains broken codes',()=>{
  const M=context(chat().host).model;
  const current=M.normalize({...M.defaults,showOnLaunch:true,objectiveWords:'守护者',fadeSeconds:30,fadeMode:'timed',artwork:true});
  const merged=M.importTheme(JSON.stringify({font:'Arial',showPings:false,showOnLaunch:false,objectiveWords:'x',artwork:true,artworkOpacity:90}),current,false);
  assert.equal(merged.font,'Arial');assert.equal(merged.showPings,false);assert.equal(merged.showOnLaunch,true);
  assert.equal(merged.objectiveWords,'守护者');assert.equal(merged.fadeSeconds,30);assert.equal(merged.preset,'custom');
  assert.equal(merged.artwork,false,'no artwork compiled in');assert.equal(merged.artworkOpacity,current.artworkOpacity);
  const withArt=M.importTheme(JSON.stringify({artwork:true,artworkOpacity:90}),M.defaults,true);
  assert.equal(withArt.artwork,true);assert.equal(withArt.artworkOpacity,90);
  assert.equal(M.importTheme(M.encode(M.preset('rivals')),current,false).preset,'rivals');
  assert.throws(()=>M.importTheme('switchboard:%E0%A4%A',current,false),/damaged/);
  assert.throws(()=>M.importTheme('hello there',current,false),/not a theme code/);
  assert.throws(()=>M.importTheme('x'.repeat(12001),current,false),/too large/);
  assert.throws(()=>M.importTheme('{"fontSize":"big"}',current,false),/must be a number/);
});

test('custom fade waits from closing chat, shows new messages and preserves native expiry',()=>{
  const c=chat(),message=c.row('Text','keep this visible'),clock={now:1000},r=context(c.host,{fadeMode:'timed',fadeSeconds:10},clock);
  message.row.AddClass('Expired');clock.now=6000;r.tick();
  assert(!message.row.BHasClass('SBTimedOut'));assert(message.row.BHasClass('Expired'));
  clock.now=12000;r.tick();assert(message.row.BHasClass('SBTimedOut'));
  c.host.AddClass('ChatExpanded');r.tick();assert(!message.row.BHasClass('SBTimedOut'));
  c.host.SetHasClass('ChatExpanded',false);clock.now=13000;r.tick();
  clock.now=22500;r.tick();assert(!message.row.BHasClass('SBTimedOut'));
  clock.now=23500;r.tick();assert(message.row.BHasClass('SBTimedOut'));
  const fresh=c.row('Text','new message');r.tick();assert(!fresh.row.BHasClass('SBTimedOut'));
  r.send({...r.model.defaults,fadeMode:'always'},24000);r.tick();
  assert(!message.row.BHasClass('SBTimedOut'));assert(c.host.BHasClass('SBCustomFade'));
  r.send({...r.model.defaults,fadeMode:'native'},25000);r.tick();
  assert(!c.host.BHasClass('SBCustomFade'));assert(message.row.BHasClass('Expired'));
});

test('incoming native rows observed after their transient live state get their own timer',()=>{
  const c=chat(),history=c.row('Text','old history','Expired'),clock={now:1000};
  const r=context(c.host,{fadeMode:'timed',fadeSeconds:10},clock);
  assert(history.row.BHasClass('SBTimedOut'));
  // Native chat.xml creates rows Expired. The engine may toggle that class
  // between scans; simulate a remote message already Expired when first seen.
  clock.now=2000;const incoming=c.row('Text','remote message','Expired');r.tick();
  assert(!incoming.row.BHasClass('SBTimedOut'));assert(incoming.row.BHasClass('Expired'));
  assert.equal(c.host.FindChildTraverse('ChatLinesArea').style.backgroundColor,r.model.rgba(r.model.defaults.background,r.model.defaults.backgroundOpacity));
  clock.now=11999;r.tick();assert(!incoming.row.BHasClass('SBTimedOut'));
  clock.now=12000;r.tick();assert(incoming.row.BHasClass('SBTimedOut'));
  // Native rows can be populated after the first scan or reused for new text.
  const pending=c.row('Text','','Expired');r.tick();clock.now=13000;
  pending.label.text='late remote text';r.tick();clock.now=22500;r.tick();
  assert(!pending.row.BHasClass('SBTimedOut'));clock.now=23000;r.tick();assert(pending.row.BHasClass('SBTimedOut'));
  const ping=c.row('Ping','Help!','Expired');r.tick();clock.now=24000;ping.row.AddClass('PingRepeated');r.tick();
  clock.now=33500;r.tick();assert(!ping.row.BHasClass('SBTimedOut'));
  r.send({...r.model.defaults,fadeMode:'timed',fadeSeconds:10,showCallouts:false},34000);r.tick();assert(ping.row.BHasClass('SBFiltered'));
  r.send({...r.model.defaults,fadeMode:'always'},34001);r.tick();assert(!history.row.BHasClass('SBTimedOut'));
  r.send({...r.model.defaults,fadeMode:'native'},34002);r.tick();assert(!c.host.BHasClass('SBCustomFade'));assert(incoming.row.BHasClass('Expired'));
  r.send({...r.model.defaults,fadeMode:'timed',fadeSeconds:10},34003);r.tick();assert(history.row.BHasClass('SBTimedOut'));
  c.host.AddClass('ChatExpanded');r.tick();assert(!incoming.row.BHasClass('SBTimedOut'));
  assert.deepEqual(c.controls.FindChildTraverse('ChatInput').events,{});
});

test('custom fade explicitly overrides native expired rows only while chat is closed',()=>{
  const css=read('src/panorama/styles/switchboard.css');
  assert.match(css,/CitadelChat\.SBCustomFade:not\(\.ChatExpanded\) \.ChatMessage\.Expired\s*\{\s*opacity:\s*1;/);
  assert.match(css,/CitadelChat\.SBCustomFade:not\(\.ChatExpanded\) \.ChatMessage\.SBTimedOut\s*\{\s*opacity:\s*0;/);
});
test('hidden mode hides lines only while chat is closed, as the help text says',()=>{
  const css=read('src/panorama/styles/switchboard.css');
  assert.match(css,/CitadelChat\.SBHidden:not\(\.ChatExpanded\) #ChatLinesArea\s*\{\s*visibility:\s*collapse;/);
  assert.doesNotMatch(css,/^\.SBHidden #ChatLinesArea/m);
});

test('communication categories separate typed text, callouts, responses, world pings and objectives',()=>{
  const r=context(chat().host),M=r.model,d=M.defaults;
  assert.equal(d.showOnLaunch,false);
  assert.equal(M.category(true,"I'm with you!",false,d),'response');
  assert.equal(M.category(true,'On my way!',false,d),'callout');
  assert.equal(M.category(true,'Defend the Patron',false,d),'objective');
  assert.equal(M.category(true,'Enemy spotted',false,d),'ping');
  assert.equal(M.category(false,'Defend the Patron',false,d),'text');
  assert.equal(M.category(true,'Nocturne spotted',false,d),'ping');
  assert.equal(M.category(true,'Pushing now',false,d),'ping','whole words for Latin text');
  const onlyText=M.messagePreset('text',d);
  for(const kind of ['ping','response','callout','objective','system'])assert.equal(M.allows(kind,onlyText),false);
  assert.equal(M.allows('text',onlyText),true);
  const themed=M.preset('rivals',{...d,fadeMode:'always',showResponses:false});
  assert.equal(themed.fadeMode,'always');assert.equal(themed.showResponses,false);assert.equal(themed.showOnLaunch,false);
});
test('words without spaces or Latin letters match anywhere in the ping',()=>{
  const M=context(chat().host).model,d=M.defaults;
  const zh={...d,objectiveWords:'守护者,中路首领',calloutWords:'我来了',responseWords:'跟着你'};
  assert.equal(M.category(true,'攻击守护者',false,zh),'objective');
  assert.equal(M.category(true,'我来了！',false,zh),'callout');
  assert.equal(M.category(true,'我跟着你',false,zh),'response');
  assert.equal(M.category(true,'敌人出现',false,zh),'ping');
  const ru={...d,objectiveWords:'хранител'};
  assert.equal(M.category(true,'Защитите хранителя',false,ru),'objective');
  const ko={...d,calloutWords:'가는 중'};assert.equal(M.category(true,'지금 가는 중!',false,ko),'callout');
  assert.equal(M.compileWords(' A , ,b ').length,2);
});

test('response phrases mentioning an objective obey the response filter',()=>{
  const c=chat(),response=c.row('Ping',"I'm with you at the Patron"),
    objective=c.row('Ping','Defend the Patron'),typed=c.row('Text',"I'm with you at the Patron");
  const r=context(c.host,{showResponses:false,showObjectives:true,showText:true});
  assert(response.row.BHasClass('SBFiltered'));
  assert(!objective.row.BHasClass('SBFiltered'));
  assert(!typed.row.BHasClass('SBFiltered'));
  assert.equal(r.model.category(true,"I'm with you at the Patron",false,r.model.defaults),'response');
  assert.equal(r.model.category(true,'Defend the Patron',false,r.model.defaults),'objective');
  assert.equal(r.model.category(false,"I'm with you at the Patron",false,r.model.defaults),'text');
});

test('system filter uses the game\'s SenderLocalClient snippet, not invented classes',()=>{
  const c=chat(),local=c.row('Text','Player joined'),invented=c.row('Text','normal line','IsSystem SystemMessage'),child=c.row('Text','child marker');
  local.image.AddClass('SenderLocalClient');new Panel('Panel',child.image,'','SenderLocalClient');
  const r=context(c.host,{showSystem:false});
  assert(local.row.BHasClass('SBFiltered'));assert(child.row.BHasClass('SBFiltered'));assert(!invented.row.BHasClass('SBFiltered'));
  assert.match(read('src/panorama/scripts/switchboard_runtime.vts'),/"System messages"/);
  assert.doesNotMatch(read('src/panorama/scripts/switchboard_runtime.vts'),/"IsSystem"|"SystemMessage"/);
});

test('startup popup stays closed by default and own-message filtering is independent',()=>{
  const c=chat(),own=c.row('Text','my line','IsSelf'),other=c.row('Text','their line'),r=context(c.host);
  r.jobs.filter(j=>j.delay===.5).forEach(j=>j.fn());
  assert(!r.events.some(e=>e[0]==='UIShowCustomLayoutPopup'));
  r.send({...r.model.defaults,showOwnMessages:false});r.tick();
  assert(own.row.BHasClass('SBFiltered'));assert(!other.row.BHasClass('SBFiltered'));
});

test('visible native acknowledgement portraits become bounded, independently filtered response summaries',()=>{
  const c=chat(),bar=new Panel('CitadelHudTopBarChat',c.host.GetParent(),'top'),messages=new Panel('Panel',bar,'Messages');
  const ping=new Panel('Panel',messages,'','ChatMessage HasResponse'),label=new Panel('Label',ping,'MessageText');label.text='Need <b>Help!</b>';
  const heroes=new Panel('Panel',ping,'ResponseHeroes');new Panel('Panel',heroes,'','ResponseHero');
  const secondBar=new Panel('CitadelHudTopBarChat',c.host.GetParent(),'second'),secondMessages=new Panel('Panel',secondBar,'Messages');
  const secondPing=new Panel('Panel',secondMessages,'','ChatMessage HasResponse Expired'),secondHeroes=new Panel('Panel',secondPing,'ResponseHeroes');
  new Panel('Panel',secondHeroes,'','ResponseHero');
  const clock={now:1000},r=context(c.host,{fadeMode:'timed',fadeSeconds:3},clock);
  assert.equal(c.messages.children.length,1);assert(c.messages.children[0].BHasClass('SBResponse'));
  const contents=c.messages.children[0].FindChildTraverse('MessageContents');assert.equal(shown(contents.children[0]),"I'm with you · Need Help!");
  r.tick();assert.equal(c.messages.children.length,1);
  r.send({...r.model.defaults,showResponses:false});r.tick();assert(c.messages.children[0].BHasClass('SBFiltered'));
  new Panel('Panel',heroes,'','ResponseHero');r.tick();assert.equal(c.messages.children.length,2);
  ping.AddClass('Expired');new Panel('Panel',heroes,'','ResponseHero');r.tick();assert.equal(c.messages.children.length,2);
  clock.now=4000;secondPing.SetHasClass('Expired',false);r.tick();assert.equal(c.messages.children.length,3);
  clock.now=5000;r.send({...r.model.defaults,fadeMode:'timed',fadeSeconds:3},5000);r.tick();
  assert(c.messages.children[0].BHasClass('SBTimedOut'));
  assert(!r.events.some(e=>JSON.stringify(e).includes('Need Help')));
});

test('character names are default, both/player modes restore correctly, and portrait captions are separate',()=>{
  const c=chat(),root=c.host.GetParent();roster(root,'Player','Ivy');
  const line=c.row('Text','hello'),r=context(c.host,{showPortraits:true});
  assert.equal(r.model.defaults.nameMode,'hero');assert.equal(displayed(line),'Ivy');
  assert.equal(line.name.text,'Player','the native label keeps its binding');
  const order=line.name.GetParent().children.map(p=>p.id||[...p.classes][0]);assert.deepEqual(order,['name','SBSenderName','SBColon']);
  assert.equal(shown(line.row.FindChildTraverse('SBPortraitCaption')),'Ivy');
  r.send({...r.model.defaults,mode:'native',showPortraits:true},1);r.tick();
  assert.equal(line.row.FindChildTraverse('SBPortraitCaption').visible,false);
  r.send({...r.model.defaults,nameMode:'both'},2);r.tick();assert.equal(displayed(line),'Ivy (Player)');
  r.send({...r.model.defaults,nameMode:'player'},3);r.tick();assert.equal(displayed(line),'Player');
  r.send({...r.model.defaults,nameMode:'hero'},4);r.tick();assert.equal(displayed(line),'Ivy');
  line.name.text='Different player';r.tick();assert.equal(displayed(line),'Different player');
  const themed=r.model.preset('rivals',{...r.model.defaults,nameMode:'both',showPortraits:true,showPortraitNames:false});
  assert.equal(themed.nameMode,'both');assert.equal(themed.showPortraitNames,false);assert.equal(themed.showPortraits,true);
});
test('a row keeps the character it was sent as when the player changes character',()=>{
  const c=chat(),root=c.host.GetParent(),hero=roster(root,'Player','Ivy'),clock={now:1000};
  const old=c.row('Text','from last match'),r=context(c.host,{},clock);assert.equal(displayed(old),'Ivy');
  hero.text='Dynamo';clock.now=2500;r.tick();
  const fresh=c.row('Text','new match');r.tick();
  assert.equal(displayed(old),'Ivy');assert.equal(displayed(fresh),'Dynamo');
});
test('player names are shown as plain text, with a leading # guarded',()=>{
  const c=chat(),root=c.host.GetParent();roster(root,'{s:message_text}','Ivy');roster(root,'#Citadel_Hud_ChatDisabled','Seven');
  const a=c.row('Text','hi','','{s:message_text}'),b=c.row('Text','hi','','#Citadel_Hud_ChatDisabled');
  context(c.host,{nameMode:'both'});
  // In game, .text from script is literal for {s:...}; never bind a dialog-variable template.
  const oursA=a.row.FindChildTraverse('SBSenderName'),oursB=b.row.FindChildTraverse('SBSenderName');
  assert.equal(oursA.text,'Ivy ({s:message_text})');
  assert.equal(oursB.text,'Seven (#Citadel_Hud_ChatDisabled)');
  assert(!oursA.text.includes('sb_text')&&!oursB.text.includes('sb_text'));
});

test('match pings are cleared on entering the hideout once; new hideout pings show',()=>{
  const c=chat(),hud=c.host.GetParent();hud.paneltype='CitadelHud';hud.id='Hud';
  const time=new Panel('Label',hud,'GameTime');time.text='12:20';
  const text=c.row('Text','party message'),ping=c.row('Ping','Defend the Patron'),r=context(c.host,{fadeMode:'always'});
  assert(!ping.row.BHasClass('SBStale'));
  hud.AddClass('InHideout');r.tick();assert(ping.row.BHasClass('SBStale'));assert(ping.row.BHasClass('SBFiltered'));assert(!text.row.BHasClass('SBStale'));
  const queued=c.row('Ping','hideout ping');r.tick();r.tick();assert(!queued.row.BHasClass('SBStale'));assert(!queued.row.BHasClass('SBFiltered'));
  hud.SetHasClass('InHideout',false);time.text='0:10';r.tick();
  const fresh=c.row('Ping','new match ping');r.tick();assert(!fresh.row.BHasClass('SBStale'));assert(ping.row.BHasClass('SBFiltered'));
  time.text='2:10';r.tick();time.text='0:00';r.tick();assert(fresh.row.BHasClass('SBStale'));
  const pre=c.row('Ping','another match');r.tick();hud.AddClass('GameStatePreGame');r.tick();assert(pre.row.BHasClass('SBStale'));
  assert(!r.events.some(e=>JSON.stringify(e).includes('hideout ping')));
});

test('artwork is offered and drawn only when the build compiled it in',()=>{
  const c=chat(),r=context(c.host,{artwork:true});
  assert.equal(c.host.FindChildTraverse('SBChatArtwork'),null);
  const host=popup(),p=context(host,{artwork:true});
  host.FindChildTraverse('SBTab_Theme').events.onactivate();
  assert.equal(host.FindChildTraverse('SBToggle_artwork'),null);
  const code=host.FindChildTraverse('SBThemeCode');code.text=JSON.stringify({artwork:true,font:'Georgia'});
  host.FindChildTraverse('SBImport').events.onactivate();
  const sent=JSON.parse(p.events.filter(e=>e[0]==='ClientUI_FireOutput').at(-1)[1]).settings;
  assert.equal(sent.artwork,false);assert.equal(sent.font,'Georgia');
  const c2=chat(),r2=context(c2.host,{artwork:true},{now:1000},{boot:{hasArtwork:true}});
  assert(c2.host.FindChildTraverse('SBChatArtwork'));
  const host2=popup();context(host2,{artwork:true},{now:1000},{boot:{hasArtwork:true}});
  host2.FindChildTraverse('SBTab_Theme').events.onactivate();assert(host2.FindChildTraverse('SBToggle_artwork'));
  void r;void r2;
});

test('reused or late-filled rows are styled again',()=>{
  const c=chat(),line=c.row('Text','hello'),r=context(c.host),d=r.model.defaults;
  assert.equal(line.label.style.color,d.textColor);
  line.contents.SetHasClass('Text',false);line.contents.AddClass('Ping');line.label.text='On my way!';r.tick();
  assert.equal(line.label.style.color,d.pingColor);
  const late=new Panel('Label',line.contents,'');late.text='more';r.tick();assert.equal(late.style.fontSize,d.fontSize+'px');
  line.row.AddClass('IsEnemy');r.tick();assert.equal(line.name.style.color,d.enemyColor);
});

test('top-bar search starts from the HUD and is not starved by a large UI tree',()=>{
  const c=chat(),hud=c.host.GetParent();hud.paneltype='CitadelHud';
  const outer=new Panel('Panel',null,'outer');hud.parent=outer;
  for(let i=0;i<7000;i++)new Panel('Panel',outer,'filler'+i);outer.children.push(hud);
  roster(hud,'Player','Ivy');new Panel('Label',hud,'GameTime').text='1:00';
  const line=c.row('Text','hello');context(c.host);assert.equal(displayed(line),'Ivy');
});

test('settings controls: no-op colour edits, kept keys, timer steps and duplicate guards',()=>{
  const host=popup(),r=context(host),M=r.model;
  host.FindChildTraverse('SBPreset_league').events.onactivate();
  host.FindChildTraverse('SBTab_Theme').events.onactivate();
  const entry=host.FindChildTraverse('SBEntry_textColor');entry.text=M.presets.league.values.textColor.toUpperCase();entry.events.onblur();
  const sent=()=>JSON.parse(r.events.filter(e=>e[0]==='ClientUI_FireOutput').at(-1)[1]).settings;
  assert.equal(sent().preset,'league');
  host.FindChildTraverse('SBTab_Style').events.onactivate();
  host.FindChildTraverse('SBInc_side').events.onactivate();assert.equal(sent().preset,'league');assert.equal(sent().side,M.defaults.side+10);
  host.FindChildTraverse('SBChoice_anchor_right').events.onactivate();assert.equal(sent().preset,'league');
  host.FindChildTraverse('SBInc_fontSize').events.onactivate();assert.equal(sent().preset,'custom');
  for(const key of M.keptKeys)assert(key in M.defaults);
  // Visible for: only shown for the custom timer.
  host.FindChildTraverse('SBChoice_fadeMode_native').events.onactivate();assert.equal(host.FindChildTraverse('SBValue_fadeSeconds'),null);
  host.FindChildTraverse('SBChoice_fadeMode_timed').events.onactivate();assert(host.FindChildTraverse('SBValue_fadeSeconds'));
  let v=0;const up=[];for(let i=0;i<40&&v<120;i++){v=M.stepFade(v,1);up.push(v);}
  assert.deepEqual(up.slice(0,11),[1,2,3,4,5,6,7,8,9,10,15]);assert.equal(up.at(-1),120);assert.equal(up.length,32);
  assert.equal(M.stepFade(120,1),120);assert.equal(M.stepFade(15,-1),10);assert.equal(M.stepFade(10,-1),9);assert.equal(M.stepFade(0,-1),0);assert.equal(M.stepFade(12,-1),10);assert.equal(M.stepFade(12,1),15);
  // Close twice only closes once.
  host.FindChildTraverse('SBDone').events.onactivate();host.FindChildTraverse('SBDone').events.onactivate();
  assert.equal(r.events.filter(e=>e[0]==='UIPopupButtonClicked').length,1);
});
test('double clicks open one popup and a second runtime copy stops the first loop',()=>{
  const c=chat(),clock={now:1000},r=context(c.host,{},clock);
  r.ctx.SwitchboardOpen();r.ctx.SwitchboardOpen();assert.equal(r.events.filter(e=>e[0]==='UIShowCustomLayoutPopup').length,1);
  clock.now=3000;r.ctx.SwitchboardOpen();assert.equal(r.events.filter(e=>e[0]==='UIShowCustomLayoutPopup').length,2);
  const second=context(c.host,{},clock);const before=r.jobs.length;r.tick();
  assert.equal(r.jobs.length,before,'old loop does not reschedule');assert.equal(r.unregistered.length,1);
  second.tick();assert(second.jobs.length>1);
});
test('in-game text uses the plain names and no slogans',()=>{
  const files=['src/panorama/scripts/switchboard_runtime.vts','src/panorama/scripts/switchboard_shared.vts','src/panorama/layout/switchboard_panel.xml'].map(read).join('\n');
  for(const banned of ['Warm ink','FIND YOUR FREQUENCY','familiar voice','KEEP PLAYING','CHAT WORKSHOP','Launch with Switchboard','SWITCHBOARD  /  CHAT','Unrecognized','customizer','→'])
    assert(!files.includes(banned),banned);
  const M=context(chat().host).model;
  assert.deepEqual(Object.values(M.presets).map(p=>p.name),['Default','Overwatch 2 style','Marvel Rivals style','League of Legends style','Deadlock']);
  assert.match(files,/"CHAT MOD"/);assert.match(files,/\["Styled", "Deadlock", "Hidden"\]/);
});

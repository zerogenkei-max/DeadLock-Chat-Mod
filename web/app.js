(function () {
  'use strict';
  const M = window.SwitchboardModel;
  const token = document.querySelector('meta[name="switchboard-token"]').content;
  const $ = id => document.getElementById(id);
  let cfg = M.clone(M.defaults), state = {}, saveTimer, toastTimer, saving = false, dirty = false, connected = false;
  let artworkUrl = '', artworkLoaded = false;

  const CUSTOM_NOTE = 'Custom: your changes on top of a preset.';
  const samples = [
    { kind: 'text', hero: 'Ivy', player: 'Nightjar', text: 'let’s take the next fight together' },
    { kind: 'callout', hero: 'Dynamo', player: 'Moss', text: 'On my way!' },
    { kind: 'response', hero: 'Haze', player: 'Beacon', text: 'I’m with you!' },
    { kind: 'objective', hero: 'Seven', player: 'Rook', text: 'Attack the Walker' },
    { kind: 'text', hero: 'Paradox', player: 'You', text: 'ok, going in after the next wave', own: true },
    { kind: 'system', text: 'Example system message' }
  ];

  // Keys a preset keeps from the current settings; changing one doesn't make the preset "Custom".
  const keptKeys = new Set(M.keptKeys || []);
  // Visible-for timer values, using the game's own steps (M.stepFade).
  const fadeValues = [0];
  while (fadeValues[fadeValues.length - 1] < 120 && fadeValues.length < 200) fadeValues.push(M.stepFade(fadeValues[fadeValues.length - 1], 1));
  const nearestFade = v => fadeValues.reduce((best, x, i) => Math.abs(x - v) < Math.abs(fadeValues[best] - v) ? i : best, 0);

  async function api(path, data, raw) {
    const headers = { 'X-Switchboard-Token': token };
    if (data !== undefined && !raw) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { method: data === undefined ? 'GET' : 'POST', headers, body: data === undefined ? undefined : raw ? data : JSON.stringify(data) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'The Windows customiser couldn’t do that.');
    return result;
  }
  function toast(message, error) {
    const t = $('toast'); t.textContent = message; t.className = 'toast visible' + (error ? ' error' : '');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('visible'), error ? 7000 : 4000);
  }
  function elt(tag, cls, content) {
    const e = document.createElement(tag); if (cls) e.className = cls; if (content !== undefined) e.textContent = content; return e;
  }

  function update(key, value) {
    try { cfg = M.normalize({ ...cfg, [key]: value, preset: keptKeys.has(key) ? cfg.preset : 'custom' }); }
    catch (error) { toast(error.message, true); return; }
    renderPresetState(); syncDisabled(); renderPreview(); scheduleSave();
  }
  function syncDisabled() {
    const set = (key, off) => { const e = $('field-' + key); if (e) e.disabled = off; };
    set('fadeSeconds', cfg.fadeMode !== 'timed');
    set('nameMode', !cfg.showNames);
    set('showPortraitNames', !cfg.showPortraits);
    set('artwork', !state.artwork);
  }
  function scheduleSave() { dirty = true; clearTimeout(saveTimer); saveTimer = setTimeout(save, 350); renderSaveState(); }
  async function save() {
    clearTimeout(saveTimer);
    if (saving) { scheduleSave(); return; }
    saving = true; const data = JSON.stringify(cfg);
    try {
      state = await api('/api/config', cfg);
      if (data === JSON.stringify(cfg)) dirty = false;
      if (state.settings && state.settings.artwork !== cfg.artwork) { cfg.artwork = state.settings.artwork; renderControls(); }
      renderStatus();
    } catch (error) { toast(error.message, true); dirty = false; renderStatus(); }
    finally { saving = false; }
  }

  // One row per setting: label on the left, control on the right.
  function subheading(parent, text) { parent.append(elt('h3', 'subheading', text)); }
  function hint(parent, text) { parent.append(elt('p', 'hint', text)); }
  function control(parent, key, label, kind, options) {
    options = options || {};
    const row = elt('div', 'row'), name = elt('label', 'label', label), id = 'field-' + key;
    name.htmlFor = id; row.append(name);
    let input;
    if (kind === 'select') {
      input = document.createElement('select');
      (options.items || M.enums[key].map(v => [v, v])).forEach(([value, text]) => { const o = elt('option', '', text); o.value = value; input.append(o); });
      input.value = cfg[key]; input.addEventListener('change', () => update(key, input.value)); row.append(input);
    } else if (kind === 'toggle') {
      const wrap = elt('span', 'switch'); input = document.createElement('input');
      input.type = 'checkbox'; input.setAttribute('role', 'switch'); input.checked = cfg[key];
      input.addEventListener('change', () => update(key, input.checked)); wrap.append(input, elt('span', 'track')); row.append(wrap);
    } else if (kind === 'color') {
      input = document.createElement('input'); input.type = 'color'; input.value = cfg[key];
      const value = elt('span', 'value', cfg[key]), wrap = elt('span', 'colour');
      input.addEventListener('input', () => { value.textContent = input.value; update(key, input.value); });
      wrap.append(value, input); row.append(wrap);
    } else if (kind === 'text') {
      row.classList.add('stacked');
      input = document.createElement('input'); input.type = 'text'; input.value = cfg[key]; input.maxLength = 400; input.spellcheck = false;
      input.addEventListener('change', () => update(key, input.value)); row.append(input);
    } else if (kind === 'fade') {
      input = document.createElement('input'); input.type = 'range';
      input.min = 0; input.max = fadeValues.length - 1; input.step = 1; input.value = nearestFade(cfg[key]);
      const unit = options.unit || '', output = elt('output', 'value', cfg[key] + unit), wrap = elt('span', 'slider');
      output.htmlFor = id;
      input.addEventListener('input', () => { const v = fadeValues[Number(input.value)]; input.setAttribute('aria-valuetext', v + ' seconds'); output.textContent = v + unit; update(key, v); });
      wrap.append(input, output); row.append(wrap);
    } else {
      input = document.createElement('input'); input.type = 'range';
      [input.min, input.max] = M.numeric[key]; input.step = options.step || 1; input.value = cfg[key];
      const unit = options.unit || '', output = elt('output', 'value', cfg[key] + unit), wrap = elt('span', 'slider');
      output.htmlFor = id;
      input.addEventListener('input', () => { output.textContent = input.value + unit; update(key, Number(input.value)); });
      wrap.append(input, output); row.append(wrap);
    }
    input.id = id; parent.append(row); return input;
  }

  function renderControls() {
    const s = $('panel-style'), m = $('panel-messages'), colours = $('colours'), art = $('art-controls');
    [s, m, colours, art].forEach(x => x.replaceChildren());

    control(s, 'mode', 'Chat display', 'select', { items: [['styled', 'Styled'], ['native', 'Deadlock'], ['hidden', 'Hidden']] });
    control(s, 'fadeMode', 'After closing chat', 'select', { items: [['native', 'Game timing'], ['timed', 'Custom timer'], ['always', 'Always visible']] });
    control(s, 'fadeSeconds', 'Visible for', 'fade', { unit: ' s' });
    hint(s, 'The timer starts when you close chat. Each new message starts its own timer.');
    control(s, 'font', 'Font', 'select', { items: M.enums.font.map(f => [f, f === 'Radiance' ? 'Radiance (game font)' : f]) });
    control(s, 'fontSize', 'Font size', 'range', { unit: ' px' });
    control(s, 'bold', 'Bold text', 'toggle');
    control(s, 'textShadow', 'Text shadow', 'toggle');
    control(s, 'backgroundOpacity', 'Background opacity', 'range', { unit: '%', step: 2 });
    control(s, 'textOpacity', 'Text opacity', 'range', { unit: '%', step: 2 });
    subheading(s, 'Size and position');
    control(s, 'width', 'Width', 'range', { step: 10 });
    control(s, 'height', 'History height', 'range', { step: 10 });
    control(s, 'anchor', 'Screen edge', 'select', { items: [['left', 'Left'], ['center', 'Centre'], ['right', 'Right']] });
    control(s, 'side', 'Side margin', 'range', { step: 4 });
    control(s, 'bottom', 'Bottom margin', 'range', { step: 5 });
    control(s, 'spacing', 'Line spacing', 'range');
    control(s, 'padding', 'Panel padding', 'range');
    control(s, 'radius', 'Corner radius', 'range');
    hint(s, 'Sizes use the game’s UI units, as on a 1080p screen.');
    subheading(s, 'Other');
    control(s, 'nativeInput', 'Deadlock-style input bar', 'toggle');
    control(s, 'showOnLaunch', 'Open the options when the game starts', 'toggle');

    const quick = elt('div', 'button-row');
    [['text', 'Text only'], ['comms', 'Text and pings'], ['all', 'Everything']].forEach(([id, label]) => {
      const b = elt('button', 'button', label); b.type = 'button';
      b.addEventListener('click', () => { cfg = M.messagePreset(id, cfg); renderControls(); renderPreview(); scheduleSave(); });
      quick.append(b);
    });
    m.append(quick);
    control(m, 'showText', 'Player messages', 'toggle');
    control(m, 'showPings', 'Other pings', 'toggle');
    control(m, 'showCallouts', 'Chat wheel callouts', 'toggle');
    control(m, 'showResponses', 'Ping replies (“I’m with you”)', 'toggle');
    control(m, 'showObjectives', 'Objective pings', 'toggle');
    control(m, 'showSystem', 'System messages', 'toggle');
    control(m, 'showOwnMessages', 'My own messages and pings', 'toggle');
    hint(m, 'Filters only hide lines. Deadlock’s channels and mute settings still apply.');
    subheading(m, 'On each line');
    control(m, 'showChannel', 'Channel label', 'toggle');
    control(m, 'showNames', 'Sender', 'toggle');
    control(m, 'nameMode', 'Sender shown as', 'select', { items: [['hero', 'Character'], ['player', 'Player'], ['both', 'Character (Player)']] });
    control(m, 'showPortraits', 'Portraits', 'toggle');
    control(m, 'showPortraitNames', 'Character name under portrait', 'toggle');
    subheading(m, 'Ping words');
    hint(m, 'Pings are sorted by the words in them. Separate words with commas, and add your game language’s words if needed.');
    control(m, 'objectiveWords', 'Objective words', 'text');
    control(m, 'calloutWords', 'Callout words', 'text');
    control(m, 'responseWords', 'Reply words', 'text');

    subheading(colours, 'Colours');
    [['background', 'Panel'], ['textColor', 'Message text'], ['teamColor', 'Team names'], ['selfColor', 'Your name'],
      ['enemyColor', 'Enemy names'], ['pingColor', 'Pings'], ['accent', 'Input bar']].forEach(([k, l]) => control(colours, k, l, 'color'));

    control(art, 'artwork', 'Show background image', 'toggle');
    control(art, 'artworkOpacity', 'Image opacity', 'range', { unit: '%', step: 2 });
    if (!state.artwork) hint(art, 'Choose an image first.');
    renderPresetState(); syncDisabled();
  }

  function renderPresets() {
    const list = $('presets'); list.replaceChildren();
    Object.keys(M.presets).forEach(id => {
      const b = elt('button', 'preset', M.presets[id].name);
      b.type = 'button'; b.dataset.preset = id;
      b.addEventListener('click', () => { cfg = M.preset(id, cfg); renderControls(); renderPreview(); scheduleSave(); });
      list.append(b);
    });
  }
  function renderPresetState() {
    document.querySelectorAll('[data-preset]').forEach(b => {
      const on = b.dataset.preset === cfg.preset; b.classList.toggle('selected', on); b.setAttribute('aria-pressed', String(on));
    });
    $('preset-note').textContent = M.presets[cfg.preset] ? M.presets[cfg.preset].note : CUSTOM_NOTE;
  }

  // The preview shows part of a 1920 x 1080 game screen: 960 units wide, the bottom 720 tall.
  const VIEW_W = 960, VIEW_H = 720;
  function renderPreview() {
    const scene = $('scene'), chat = $('chat-preview'), lines = $('chat-lines'), input = $('chat-input');
    const k = scene.clientWidth / VIEW_W, u = n => (n * k).toFixed(1) + 'px';
    scene.style.backgroundPosition = (cfg.anchor === 'right' ? '100%' : cfg.anchor === 'center' ? '50%' : '0%') + ' 100%';
    chat.className = 'chat ' + cfg.mode;
    chat.style.width = u(cfg.width);
    chat.style.left = cfg.anchor === 'left' ? u(cfg.side) : cfg.anchor === 'center' ? u(VIEW_W / 2 - cfg.width / 2) : 'auto';
    chat.style.right = cfg.anchor === 'right' ? u(cfg.side) : 'auto';
    chat.style.bottom = u(cfg.bottom);
    chat.style.fontFamily = cfg.font === 'Radiance' ? '' : '"' + cfg.font + '", sans-serif';
    chat.style.fontSize = u(cfg.fontSize);
    chat.style.fontWeight = cfg.bold ? '700' : '400';

    lines.style.height = u(cfg.height);
    lines.style.padding = u(cfg.padding);
    lines.style.borderRadius = u(cfg.radius);
    lines.style.backgroundColor = cfg.mode === 'styled' ? M.rgba(cfg.background, cfg.backgroundOpacity) : 'transparent';
    lines.style.setProperty('--art', cfg.mode === 'styled' && cfg.artwork && artworkUrl ? 'url("' + artworkUrl + '")' : 'none');
    lines.style.setProperty('--art-opacity', cfg.artworkOpacity / 100);
    lines.replaceChildren();
    if (cfg.mode !== 'hidden') {
      samples.filter(s => M.allows(s.kind, cfg) && (cfg.showOwnMessages || !s.own)).forEach(s => {
        const line = elt('div', 'line'), nameColour = s.own ? cfg.selfColor : cfg.teamColor, isPing = s.kind !== 'text';
        line.style.marginTop = u(cfg.spacing);
        if (cfg.mode === 'styled') {
          line.style.color = isPing ? cfg.pingColor : cfg.textColor;
          line.style.opacity = cfg.textOpacity / 100;
          line.style.textShadow = cfg.textShadow ? '0 1px 2px #000' : 'none';
        }
        if (cfg.showPortraits && s.hero) {
          const p = elt('span', 'portrait'); p.append(elt('span', 'avatar', s.hero.charAt(0)));
          if (cfg.showPortraitNames) p.append(elt('span', 'portrait-name', s.hero));
          line.append(p);
        }
        const body = elt('span', 'body');
        if (cfg.showChannel && s.hero) { const c = elt('span', 'channel', '[Allies] '); c.style.color = nameColour; body.append(c); }
        if (cfg.showNames && s.hero) { const n = elt('span', 'sender', M.displayName(s.player, s.hero, cfg.nameMode) + ': '); n.style.color = nameColour; body.append(n); }
        body.append(elt('span', 'text', s.text)); line.append(body); lines.append(line);
      });
    }
    input.style.height = u(32);
    input.style.padding = '0 ' + u(10);
    input.style.borderTopColor = cfg.nativeInput ? 'transparent' : cfg.accent;
    input.classList.toggle('native-input', cfg.nativeInput || cfg.mode === 'native');
  }

  function renderSaveState() {
    const el = $('save-state');
    el.classList.remove('warn');
    if (dirty || saving) el.textContent = 'Saving…';
    else if (state.notice) { el.textContent = state.notice; el.classList.add('warn'); }
    else if (!connected) el.textContent = '';
    else if (state.pending) el.textContent = state.gameRunning ? 'Saved. The game copy is updated after Deadlock closes.' : 'Saved. Updating the game copy…';
    else el.textContent = 'Saved' + (state.lastBuilt ? '. Game copy updated at ' + state.lastBuilt + '.' : '.');
  }
  function installText() {
    if (state.error) return [state.error, 'error'];
    if (state.gameRunning) return ['Deadlock is running. Use the in-game options for live changes; changes made here apply after the game closes.', ''];
    if (!state.gameFound) return ['Deadlock wasn’t found. Paste its folder under Game folder.', 'warn'];
    if (state.installedCopies > 1) return ['More than one copy of the chat mod is turned on. Keep one and turn the others off in Mod Manager.', 'warn'];
    if (state.installed) return ['Installed and connected. Changes are saved to the game copy automatically.', 'ok'];
    if (state.modManager && state.disabledCopies) return ['The chat mod is turned off in Deadlock Mod Manager. Turn it on there, then click Install / update.', 'warn'];
    if (state.modManager) return ['Add the chat mod in Deadlock Mod Manager and turn it on, then click Install / update to connect that copy.', ''];
    return ['Not installed yet. Install / update adds it to Deadlock’s addons folder.', ''];
  }
  function renderStatus() {
    $('version').textContent = state.version ? state.version : '';
    $('signal').classList.toggle('on', connected);
    $('connection-text').textContent = connected ? 'Customiser running' : 'Customiser not running';
    const [text, tone] = connected ? installText() : ['The Windows customiser has stopped. Open it again to save changes.', 'error'];
    $('install-status').textContent = text; $('install-status').className = 'status-text ' + tone;
    renderSaveState();
    const blocked = !connected || !!state.gameRunning || !state.gameFound;
    $('install').disabled = blocked; $('launch').disabled = blocked; $('download').disabled = !connected; $('quit').disabled = !connected;
    $('game-folder-current').textContent = state.gameFolder ? 'Using: ' + state.gameFolder : 'No folder chosen.';
    if (state.artwork && !artworkLoaded) loadArtwork();
  }
  async function loadArtwork() {
    artworkLoaded = true;
    try {
      const response = await fetch('/artwork.png', { headers: { 'X-Switchboard-Token': token } });
      if (!response.ok) throw new Error();
      if (artworkUrl) URL.revokeObjectURL(artworkUrl);
      artworkUrl = URL.createObjectURL(await response.blob()); renderPreview();
    } catch { artworkLoaded = false; }
  }
  async function poll() {
    try {
      const next = await api('/api/state');
      const hadArtwork = state.artwork;
      connected = true; state = next;
      if (!dirty && !saving && JSON.stringify(next.settings) !== JSON.stringify(cfg)) { cfg = M.normalize(next.settings); renderControls(); renderPreview(); }
      else if (hadArtwork !== next.artwork) renderControls();
      renderStatus();
    } catch { connected = false; renderStatus(); }
  }

  async function upload(file) {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 8 * 1024 * 1024) return toast('Choose a PNG, JPG or WebP image under 8 MB.', true);
    try {
      const bitmap = await createImageBitmap(file);
      const ratio = Math.min(1, 1024 / bitmap.width, 512 / bitmap.height), canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * ratio)); canvas.height = Math.max(1, Math.round(bitmap.height * ratio));
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close();
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      state = await api('/api/artwork', blob, true); cfg = M.normalize(state.settings);
      artworkLoaded = false; renderControls(); renderStatus(); renderPreview();
      toast('Image added. It shows in game after the next update.');
    } catch (error) { toast('Couldn’t use that image: ' + error.message, true); }
  }
  async function download() {
    const button = $('download'); button.disabled = true;
    try {
      const response = await fetch('/download/switchboard.zip', { headers: { 'X-Switchboard-Token': token } });
      if (!response.ok) { const r = await response.json().catch(() => ({})); throw new Error(r.error || 'Couldn’t make the ZIP.'); }
      const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
      link.href = url; link.download = state.zipName || 'Switchboard-Mod.zip'; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = !connected; }
  }
  function importTheme(value) {
    try { cfg = M.importTheme(value, cfg, !!state.artwork); renderControls(); renderPreview(); scheduleSave(); toast('Theme applied.'); }
    catch (e) { toast(e.message, true); }
  }

  // Tabs: click, or arrow keys / Home / End when a tab has focus.
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function selectTab(tab, focus) {
    tabs.forEach(t => {
      const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1;
      $(t.getAttribute('aria-controls')).hidden = !on;
    });
    if (focus) tab.focus();
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', e => {
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault(); selectTab(tabs[(next + tabs.length) % tabs.length], true);
    });
  });

  $('reset').addEventListener('click', () => { cfg = M.preset('switchboard'); renderControls(); renderPreview(); scheduleSave(); toast('Reset to Default.'); });
  window.addEventListener('resize', renderPreview);
  $('art-file').addEventListener('change', e => { upload(e.target.files[0]); e.target.value = ''; });
  $('theme-file').addEventListener('change', async e => {
    const file = e.target.files[0]; e.target.value = '';
    if (!file) return; if (file.size > 12000) return toast('Theme files must be under 12 KB.', true);
    importTheme(await file.text());
  });
  $('import-code').addEventListener('click', () => importTheme($('theme-code').value));
  $('copy-code').addEventListener('click', async () => {
    const code = M.encode(cfg); $('theme-code').value = code;
    try { await navigator.clipboard.writeText(code); toast('Theme code copied.'); } catch { $('theme-code').select(); toast('Theme code is in the box. Copy it from there.'); }
  });
  $('export-theme').addEventListener('click', () => {
    const data = new Blob([JSON.stringify(cfg, null, 2) + '\n'], { type: 'application/json' }), link = document.createElement('a');
    link.href = URL.createObjectURL(data); link.download = 'chat-mod-theme.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
  [['install', '/api/install', 'Installed. Keep only one copy turned on.'], ['launch', '/api/launch', 'Starting Deadlock…']].forEach(([id, path, message]) => $(id).addEventListener('click', async () => {
    $(id).disabled = true;
    try { if (dirty) await save(); state = await api(path, {}); toast(message); } catch (error) { toast(error.message, true); }
    renderStatus();
  }));
  $('download').addEventListener('click', download);
  $('save-folder').addEventListener('click', async () => {
    try { state = await api('/api/game-folder', { path: $('game-folder').value }); $('game-folder').value = ''; renderStatus(); toast('Game folder updated.'); }
    catch (e) { toast(e.message, true); }
  });
  $('quit').addEventListener('click', () => { const d = $('quit-dialog'); if (d.showModal) d.showModal(); else if (confirm('Quit the Windows customiser?')) quit(); });
  $('quit-dialog').addEventListener('close', () => { if ($('quit-dialog').returnValue === 'quit') quit(); });
  async function quit() {
    try { if (dirty) await save(); await api('/api/shutdown', {}); connected = false; state = {}; renderStatus(); toast('The Windows customiser has stopped.'); }
    catch (e) { toast(e.message, true); }
  }

  renderPresets(); renderControls(); renderPreview(); renderStatus(); poll(); setInterval(poll, 2500);
})();

# ═══════════════════════════════════════════════════════════════════════════════
# ui_assets.py — Subvoyant SIENA Slurmer  (part of the Slurmify project)
#
# PURPOSE
# -------
# This module holds every piece of static browser-side content that the
# Slurmify Gradio UI needs: the JavaScript that runs in the user's browser
# (INIT_JS), the CSS that styles the dark UI (CUSTOM_CSS), the base64-encoded
# GIF animations for the hover Easter eggs, and the Subvoyant icon data used
# as the browser favicon and the header logo.
#
# Nothing in this file does any audio processing.  It is purely the
# "what the browser sees and runs" layer — no numpy, no librosa, no ffmpeg.
#
# WHY DOES THIS FILE EXIST?
# -------------------------
# app.py was approaching 3,600 lines.  The two biggest contributors were
# INIT_JS (~500 lines of browser JavaScript) and CUSTOM_CSS (~1,200 lines of
# CSS spread across five concatenated blocks).  These are static strings that
# never change at runtime — moving them here lets each one be edited with
# proper syntax highlighting without scrolling past thousands of lines of
# unrelated Python, and makes app.py itself much easier to navigate.
#
# No behaviour changes.  app.py imports these names and uses them exactly as
# before.
#
# CONTENTS (in order of definition)
# ----------------------------------
#
#   INIT_JS
#       All browser-side JavaScript.  Injected into the page's <head> via
#       ui.launch(head=f"<script>\n{INIT_JS}\n</script>").
#       Internally divided into six labelled sections — see the section banners
#       inside the string for details.
#
#   CUSTOM_CSS
#       All Gradio CSS overrides.  Built across five Python string blocks
#       (one plain assignment + four += concatenations) because three of those
#       blocks embed base64 GIF data directly inside CSS background-image:url()
#       rules.  The GIF variables therefore MUST be defined before the CSS
#       blocks that reference them — which is why the GIF vars and CSS blocks
#       appear interleaved below rather than in two tidy groups.
#
#   _MAX_GIF_B64
#       Base64-encoded GIF of Max the tester.  Used in a CSS ::after rule so
#       it slides in from the right when the user hovers the MAX RANDOM radio
#       option.  Inlined to avoid extra HTTP requests and PyInstaller path
#       headaches.
#
#   _BOB_GIF_B64
#       Base64-encoded GIF of Bob.  Used in a CSS ::after rule so it rises up
#       from below the "📁 reveal temp files" button on hover.  Bob suggested
#       that feature, so he gets the Easter egg.
#
#   _HOBERMAN_GIF_B64
#       Base64-encoded GIF of Hoberman-Max.  Used in a CSS ::after rule on the
#       🎲 randomise-all button — same bottom-up spring animation as Bob's, for
#       visual consistency between the two utility buttons.
#
#   _MAX_FIRE_GIF_B64
#       Base64-encoded GIF of Max raising up and coming back down (800×556,
#       19 frames).  Used in a CSS ::after rule on #slurm-beat-mask — Max peeks
#       up from behind the chip strip when the user hovers the panel.  No CSS
#       spring: the GIF is self-animating.
#
#   _ICON_B64
#       Base64-encoded PNG of the Subvoyant / Siena cat icon.  Used as the
#       browser favicon (injected via JS in INIT_JS) and in _ICON_TAG below.
#
#   _ICON_TAG
#       Pre-assembled <a><img></a> HTML string for the clickable Subvoyant logo
#       in the page header.  Constructed from _ICON_B64 so both the favicon and
#       the header image stay in sync automatically.
#
# HOW app.py USES THESE
# ---------------------
#   from ui_assets import (
#       INIT_JS, CUSTOM_CSS,
#       _MAX_GIF_B64, _BOB_GIF_B64, _HOBERMAN_GIF_B64,
#       _ICON_B64, _ICON_TAG,
#   )
#
#   Key call sites in app.py / build_ui():
#       ui.launch(head=f"<script>\n{INIT_JS}\n</script>")
#       gr.Blocks(css=CUSTOM_CSS)
#       gr.HTML(_ICON_TAG)
#
# PYINSTALLER NOTE
# ----------------
# "ui_assets" is listed in hiddenimports in slurmify.spec.  PyInstaller does
# not auto-detect implicit imports of this kind — it MUST be listed or the
# bundled .app will crash on startup with a ModuleNotFoundError.
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# INIT_JS — Browser-side JavaScript
# ───────────────────────────────────────────────────────────────────────────────
# This entire string is injected verbatim into the page <head> at launch time:
#
#   ui.launch(head=f"<script>\n{INIT_JS}\n</script>")
#
# It must be a single JS function-expression style block — not an IIFE, not
# bare statements.  Gradio 6 silently breaks bare top-level statements in the
# head injection path (ADR-0014).
#
# INTERNAL SECTIONS (see banners inside the string):
#   § 1  AudioContext setup + Web Audio FX node graph
#   § 2  _fxWalk()      — recurse into shadow DOM to find <audio> elements
#   § 3  _bindFxChain() — one-shot binding of createMediaElementSource
#   § 4  audio_out.change handler — syncs Gradio output URL → #slurm-fx-audio
#   § 5  FX slider → Web Audio param sync (zero Python round-trip)
#   § 6  UI enhancements: hover gifs, favicon injection, keyboard shortcuts
#
# IMPORTANT: createMediaElementSource() can only be called ONCE per <audio>
# element for the lifetime of the page.  We bind to a dedicated hidden element
# <audio id="slurm-fx-audio"> that our code owns.  Never rebind, never bind to
# Gradio's WaveSurfer-managed element.  (ADR-0003)
# ═══════════════════════════════════════════════════════════════════════════════
INIT_JS = """
(function () {
    var _dbg = function(msg) { console.log('[SLURM] ' + msg); };

    _dbg('INIT_JS fired ✓');

    // ── Skin switcher ────────────────────────────────────────────────────
    // Three skins coexist in the CSS; only the one named in body[data-skin]
    // is visible. Order of precedence for picking the active skin:
    //   1. ?skin=<name> URL param
    //   2. localStorage 'slurm_skin'
    //   3. 'default'
    var _SKIN_NAMES = ['default', 'acid', 'hardware'];
    function _slurmSetSkin(name) {
        if (_SKIN_NAMES.indexOf(name) === -1) name = 'default';
        document.body.dataset.skin = name;
        try { localStorage.setItem('slurm_skin', name); } catch(e) {}
        var sel = document.getElementById('slurm-skin-picker');
        if (sel && sel.value !== name) sel.value = name;
        _dbg('skin → ' + name);
    }
    (function _slurmInitSkin() {
        var url   = new URL(window.location);
        var skin  = url.searchParams.get('skin');
        if (!skin) {
            try { skin = localStorage.getItem('slurm_skin'); } catch(e) {}
        }
        _slurmSetSkin(skin || 'default');
    })();
    window.slurmSetSkin = _slurmSetSkin;

    // ── Live playhead clock ──────────────────────────────────────────────
    var _clockTick = 0;
    (function tick() {
        var a = document.querySelector('audio');
        var c = document.getElementById('slurm-clock-wrap');
        if (c) {
            var t = (a && !isNaN(a.currentTime)) ? a.currentTime : 0;
            c.textContent = '► ' + Math.floor(t / 60) + ':'
                            + (t % 60).toFixed(2).padStart(5, '0');
        }
        _clockTick++;
        if (_clockTick === 1) _dbg('clock loop started, audio=' + (a ? 'found' : 'NOT FOUND'));
        if (_clockTick === 60) _dbg('clock @ 60 frames, clock-wrap=' + (c ? 'found' : 'NOT FOUND'));
        requestAnimationFrame(tick);
    })();

    // ── Keyboard shortcuts — I / O ─────────────────────────────────────
    // Gradio 6 applies elem_id directly to the <button> element itself,
    // NOT to a wrapper div. Try all selector forms + text-content fallback.
    function slurmFindBtn(id, text) {
        return document.querySelector('#' + id)
            || document.querySelector('#' + id + ' button')
            || Array.from(document.querySelectorAll('button')).find(function(b) {
                   return b.textContent.trim().indexOf(text) !== -1;
               });
    }
    document.addEventListener('keydown', function (e) {
        var tag = (e.target.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        if (e.key === 'i' || e.key === 'I') {
            e.preventDefault();
            var b = slurmFindBtn('slurm-in-btn', 'I ] in');
            _dbg('I key: btn=' + (b ? 'FOUND id=' + (b.id||'?') + ', clicking' : 'NOT FOUND'));
            if (b) b.click();
        }
        if (e.key === 'o' || e.key === 'O') {
            e.preventDefault();
            var b = slurmFindBtn('slurm-out-btn', 'O ] out');
            _dbg('O key: btn=' + (b ? 'FOUND id=' + (b.id||'?') + ', clicking' : 'NOT FOUND'));
            if (b) b.click();
        }
    });

    _dbg('keydown listener attached ✓');

    // ── Web Audio FX chain ───────────────────────────────────────────────
    // Inspired by: Sambego/audio-effects, noisehack.com, tomhazledine.com/web-audio-delay
    // Topology: src → distortion → ringMod → delay → phaser → destination
    var _fxCtx = null, _fxSrc = null, _fxN = null;
    var _fxP = {
        distDrive:  0,
        ringFreq:   200, ringDepth: 0,
        delayTime:  0.3, delayFb: 0.35, delayMix: 0,
        phaseRate:  1.0, phaseDepth: 0
    };

    function _fxWalk(root) {
        var found = [];
        try {
            root.querySelectorAll('audio').forEach(function(a) { found.push(a); });
            root.querySelectorAll('*').forEach(function(el) {
                if (el.shadowRoot) found = found.concat(_fxWalk(el.shadowRoot));
            });
        } catch(e) {}
        return found;
    }

    function _fxCurve(drive) {
        var n = 1024, curve = new Float32Array(n);
        var k = drive < 0.01 ? 0 : 1 + drive * 29;
        for (var i = 0; i < n; i++) {
            var x = (i / (n - 1)) * 2 - 1;
            curve[i] = k > 0 ? Math.tanh(k * x) / Math.tanh(k) : x;
        }
        return curve;
    }

    function _fxApply() {
        if (!_fxN) return;
        var p = _fxP, n = _fxN;
        // Distortion
        n.dist.curve = _fxCurve(p.distDrive);
        // Ring mod: gain = 1 + depth * sin(freq*t)
        n.ringOsc.frequency.value = p.ringFreq;
        n.ringOscAmp.gain.value   = p.ringDepth;   // oscillator amplitude = depth
        // Delay
        n.delay.delayTime.value = p.delayTime;
        n.delayFb.gain.value    = p.delayFb;
        n.delayDry.gain.value   = 1 - p.delayMix;
        n.delayWet.gain.value   = p.delayMix;
        // Phaser
        n.phaseLFO.frequency.value    = p.phaseRate;
        n.phaseLFOGain.gain.value     = 500 * p.phaseDepth;
        n.phaseDry.gain.value         = 1 - p.phaseDepth * 0.5;
        n.phaseWet.gain.value         = p.phaseDepth * 0.5;
    }

    function _fxSetup(audioEl) {
        // Idempotent: createMediaElementSource() can only be called ONCE per
        // HTMLMediaElement for its lifetime — closing the AudioContext does
        // NOT release that binding. So we wire the chain exactly once and
        // reuse it forever; new files come in via audioEl.src updates only.
        if (_fxCtx) return;

        _fxCtx = new (window.AudioContext || window.webkitAudioContext)();

        try {
            _fxSrc = _fxCtx.createMediaElementSource(audioEl);
        } catch(e) {
            _dbg('FX: createMediaElementSource failed: ' + e);
            _fxCtx = null;   // allow a retry on the next poll if it failed
            return;
        }

        // ── Distortion (WaveShaper) ──────────────────────────────────────
        var dist = _fxCtx.createWaveShaper();
        dist.curve = _fxCurve(0);
        dist.oversample = '2x';

        // ── Ring Mod (oscillator → gain.gain) ───────────────────────────
        // gain = 1.0 base + (osc output × depth) — matches Python: 1 + depth*sin(t)
        var ringGain = _fxCtx.createGain();
        ringGain.gain.value = 1.0;            // base (passthrough when depth=0)
        var ringOsc = _fxCtx.createOscillator();
        ringOsc.type = 'sine';
        ringOsc.frequency.value = _fxP.ringFreq;
        var ringOscAmp = _fxCtx.createGain();
        ringOscAmp.gain.value = 0;            // 0 = no ring mod
        ringOsc.connect(ringOscAmp);
        ringOscAmp.connect(ringGain.gain);    // adds to gain.value
        ringOsc.start();

        // ── Delay (DelayNode + feedback loop) ───────────────────────────
        var delay   = _fxCtx.createDelay(2.0);
        var delayFb = _fxCtx.createGain();
        var delayDry = _fxCtx.createGain();
        var delayWet = _fxCtx.createGain();
        var delayOut = _fxCtx.createGain();   // merge dry + wet
        delay.delayTime.value = _fxP.delayTime;
        delayFb.gain.value    = _fxP.delayFb;
        delayDry.gain.value   = 1;
        delayWet.gain.value   = 0;
        delay.connect(delayFb);
        delayFb.connect(delay);               // feedback loop
        delay.connect(delayWet);
        delayDry.connect(delayOut);
        delayWet.connect(delayOut);

        // ── Phaser (4 allpass BiquadFilters + LFO) ──────────────────────
        var phaseAP = [];
        for (var i = 0; i < 4; i++) {
            var ap = _fxCtx.createBiquadFilter();
            ap.type = 'allpass';
            ap.frequency.value = 200 * Math.pow(4, i / 3.0);
            ap.Q.value = 0.5;
            phaseAP.push(ap);
        }
        var phaseLFO     = _fxCtx.createOscillator();
        var phaseLFOGain = _fxCtx.createGain();
        phaseLFO.frequency.value  = _fxP.phaseRate;
        phaseLFOGain.gain.value   = 0;
        phaseLFO.connect(phaseLFOGain);
        phaseAP.forEach(function(ap) { phaseLFOGain.connect(ap.frequency); });
        phaseLFO.start();
        for (var j = 1; j < phaseAP.length; j++) {
            phaseAP[j - 1].connect(phaseAP[j]);
        }
        var phaseDry = _fxCtx.createGain();
        var phaseWet = _fxCtx.createGain();
        phaseDry.gain.value = 1;
        phaseWet.gain.value = 0;

        // ── Connect the full chain ───────────────────────────────────────
        _fxSrc.connect(dist);
        dist.connect(ringGain);

        ringGain.connect(delayDry);
        ringGain.connect(delay);

        delayOut.connect(phaseDry);
        delayOut.connect(phaseAP[0]);

        phaseAP[phaseAP.length - 1].connect(phaseWet);
        phaseDry.connect(_fxCtx.destination);
        phaseWet.connect(_fxCtx.destination);

        _fxN = {
            dist: dist,
            ringGain: ringGain, ringOsc: ringOsc, ringOscAmp: ringOscAmp,
            delay: delay, delayFb: delayFb, delayDry: delayDry,
            delayWet: delayWet, delayOut: delayOut,
            phaseAP: phaseAP, phaseLFO: phaseLFO, phaseLFOGain: phaseLFOGain,
            phaseDry: phaseDry, phaseWet: phaseWet
        };
        _fxApply();

        // Browsers create AudioContext suspended until a real user gesture.
        // Hook the element's 'play' event (which IS a user gesture) so the
        // context resumes the moment the user hits the play button.
        audioEl.addEventListener('play', function() {
            if (_fxCtx && _fxCtx.state === 'suspended') {
                _fxCtx.resume().catch(function(e) {
                    _dbg('FX: resume() rejected: ' + e);
                });
            }
        });
        // Best-effort early resume (works if user already interacted).
        if (_fxCtx.state === 'suspended') _fxCtx.resume();

        // Tap an AnalyserNode off the dry phase output so audio-reactive
        // viz (VU meter for hardware skin, halo pulse for acid skin) can
        // sample the same signal the user hears.
        try {
            var an = _fxCtx.createAnalyser();
            an.fftSize = 256;
            an.smoothingTimeConstant = 0.7;
            phaseDry.connect(an);
            _fxN.analyser = an;
            _fxN.analyserBuf = new Uint8Array(an.frequencyBinCount);
        } catch(e) {
            _dbg('FX: analyser tap failed: ' + e);
        }

        _dbg('FX chain ready, sr=' + _fxCtx.sampleRate);
    }

    // ── Audio-reactive viz loop (VU meter + acid halo) ──────────────────
    // One rAF loop drives both the hardware-skin VU meter and the
    // acid-skin halo around the slurmify button. The loop is always
    // running but cheaply skips work when no analyser is attached or
    // the corresponding skin is inactive (CSS keeps elements hidden).
    (function _slurmVizLoop() {
        function _rms(buf) {
            var sum = 0;
            for (var i = 0; i < buf.length; i++) {
                var v = (buf[i] - 128) / 128;
                sum += v * v;
            }
            return Math.sqrt(sum / buf.length);
        }
        function _bandAvg(buf, lo, hi) {
            var s = 0, n = Math.max(1, hi - lo);
            for (var i = lo; i < hi; i++) s += buf[i];
            return s / (n * 255);
        }

        var vu = document.getElementById('slurm-vu-meter');
        var halo = document.getElementById('slurm-go-halo');
        var skin;
        var phase = 0;

        function step() {
            phase++;
            skin = document.body && document.body.dataset
                   ? document.body.dataset.skin : 'default';
            var an = _fxN && _fxN.analyser;

            if (an && skin === 'hardware' && vu) {
                an.getByteFrequencyData(_fxN.analyserBuf);
                var ctx = vu.getContext('2d');
                var w = vu.width, h = vu.height;
                ctx.clearRect(0, 0, w, h);
                // 24 vertical bars, log-ish bin spacing.
                var bins = _fxN.analyserBuf;
                var nBars = 32;
                var barW = w / nBars;
                for (var b = 0; b < nBars; b++) {
                    var i = Math.floor(Math.pow(b / nBars, 1.6) * bins.length);
                    var v = bins[i] / 255;
                    var bh = Math.max(1, v * (h - 4));
                    // Amber LED gradient — green low, amber mid, red top
                    var grad = ctx.createLinearGradient(0, h, 0, 0);
                    grad.addColorStop(0,    '#7fff5a');
                    grad.addColorStop(0.55, '#ffb74d');
                    grad.addColorStop(0.85, '#ff5050');
                    ctx.fillStyle = grad;
                    ctx.fillRect(b * barW + 1, h - bh - 2, barW - 2, bh);
                }
            }

            if (an && skin === 'acid' && halo) {
                an.getByteTimeDomainData(_fxN.analyserBuf);
                // Energy in the lower 1/4 of bins ≈ bass band.
                var bass = _bandAvg(_fxN.analyserBuf, 0, 16);
                an.getByteFrequencyData(_fxN.analyserBuf);
                var lo = _bandAvg(_fxN.analyserBuf, 0, 8);
                // Find the slurmify button (closest primary in the same row)
                var btn = document.querySelector('button.primary, button[variant="primary"]');
                if (btn) {
                    var glow = 18 + lo * 80;
                    var spread = 4 + lo * 18;
                    btn.style.boxShadow =
                        '0 0 ' + glow + 'px ' + spread + 'px rgba(255,80,220,0.55), ' +
                        '0 0 ' + (glow * 2) + 'px ' + (spread * 2) +
                        'px rgba(60,200,255,0.35)';
                }
            } else if (skin !== 'acid') {
                // Clear inline glow when leaving acid so other skins aren't tinted.
                var btn2 = document.querySelector('button.primary, button[variant="primary"]');
                if (btn2 && btn2.style.boxShadow) btn2.style.boxShadow = '';
            }

            requestAnimationFrame(step);
        }
        // Defer first frame so the DOM has settled.
        setTimeout(function () { requestAnimationFrame(step); }, 800);
    })();

    // ── Preview-element strategy ────────────────────────────────────────
    // Gradio's gr.Audio wraps its <audio> in WaveSurfer with custom transport
    // controls; createMediaElementSource can only be called once per element
    // ever, so we use a dedicated <audio id="slurm-fx-audio"> in the FX panel.
    //
    // Two parallel mechanisms keep its src in sync with the slurm output:
    //   1. audio_out.change(js=...)  — Gradio fires when the value changes
    //      (Python side, below).
    //   2. The polling loop here     — walks the DOM for any <audio> inside
    //      Gradio's component and mirrors its src into our preview element.
    //      Required because gr.Audio's `change` event timing is unreliable
    //      (it can race with WaveSurfer's lazy mount).
    //
    // The FX chain binds on the preview element's FIRST 'play' event — a
    // real user gesture, so the AudioContext can resume immediately. Only
    // ever bound once for the page's lifetime.

    function _fxSrcUrl(audioEl) {
        // Try every place WaveSurfer/Gradio might stash the URL.
        return (audioEl && (
            audioEl.src ||
            audioEl.currentSrc ||
            audioEl.getAttribute('src') ||
            (audioEl.querySelector && audioEl.querySelector('source') &&
             audioEl.querySelector('source').src) ||
            ''
        )) || '';
    }

    var _fxLastSrc = '';
    var _fxFirstFound = false;
    setInterval(function() {
        var fxAudio = document.getElementById('slurm-fx-audio');
        if (!fxAudio) return;

        var outEl = document.getElementById('slurm-audio-out');
        if (!outEl) return;

        // Walk the (possibly nested) shadow DOM for an <audio> element with
        // a populated src — that's the file Gradio is currently serving.
        var audios = _fxWalk(outEl);
        var srcUrl = '';
        for (var i = 0; i < audios.length; i++) {
            var u = _fxSrcUrl(audios[i]);
            if (u) { srcUrl = u; break; }
        }

        if (!srcUrl) return;

        if (!_fxFirstFound) {
            _fxFirstFound = true;
            _dbg('FX: first audio src observed: ' + srcUrl);
        }

        if (srcUrl !== _fxLastSrc) {
            _fxLastSrc = srcUrl;
            _dbg('FX: mirroring src into preview element: ' + srcUrl);
            try {
                fxAudio.src = srcUrl;
                fxAudio.load();
            } catch(e) {
                _dbg('FX: setting fxAudio.src failed: ' + e);
            }
        }
    }, 400);

    // One-shot: bind the FX chain on the preview element's first play.
    // (A real user gesture — needed for AudioContext to resume.)
    var _fxBindPoll = setInterval(function() {
        var el = document.getElementById('slurm-fx-audio');
        if (!el) return;
        clearInterval(_fxBindPoll);
        el.addEventListener('play', function _onFirstPlay() {
            if (_fxCtx) return;
            _dbg('FX: first play on preview element — binding chain');
            _fxSetup(el);
        });
        _dbg('FX: preview element mounted, will bind chain on first play');
    }, 200);

    // Expose API for Gradio slider js= callbacks
    window.slurmFx = {
        setDist:       function(v) { _fxP.distDrive  = +v; _fxApply(); },
        setRingFreq:   function(v) { _fxP.ringFreq   = +v; _fxApply(); },
        setRingDepth:  function(v) { _fxP.ringDepth  = +v; _fxApply(); },
        setDelayTime:  function(v) { _fxP.delayTime  = +v; _fxApply(); },
        setDelayFb:    function(v) { _fxP.delayFb    = +v; _fxApply(); },
        setDelayMix:   function(v) { _fxP.delayMix   = +v; _fxApply(); },
        setPhaseRate:  function(v) { _fxP.phaseRate  = +v; _fxApply(); },
        setPhaseDepth: function(v) { _fxP.phaseDepth = +v; _fxApply(); },
    };
    _dbg('slurmFx API ready ✓');

    // ── DOM probe after 1 s — dump relevant element state ───────────────
    setTimeout(function() {
        // Try all selector variants to find the button
        var inBtn  = document.querySelector('#slurm-in-btn')
                  || document.querySelector('#slurm-in-btn button')
                  || slurmFindBtn('slurm-in-btn', 'I ] in');
        var outBtn = document.querySelector('#slurm-out-btn')
                  || document.querySelector('#slurm-out-btn button')
                  || slurmFindBtn('slurm-out-btn', 'O ] out');
        var inBox   = document.querySelector('#start-sec-box textarea')
                   || document.querySelector('#start-sec-box input');
        var outBox  = document.querySelector('#end-sec-box textarea')
                   || document.querySelector('#end-sec-box input');
        var audio   = document.querySelector('audio');
        _dbg('--- 1s DOM probe ---');
        _dbg('  #slurm-in-btn  button : ' + (inBtn  ? 'FOUND' : 'MISSING'));
        _dbg('  #slurm-out-btn button : ' + (outBtn ? 'FOUND' : 'MISSING'));
        _dbg('  #start-sec-box input  : ' + (inBox  ? 'FOUND' : 'MISSING'));
        _dbg('  #end-sec-box   input  : ' + (outBox ? 'FOUND' : 'MISSING'));
        _dbg('  audio element         : ' + (audio  ? 'FOUND' : 'MISSING'));
    }, 1000);

    // ── MAX RANDOM hover gif ─────────────────────────────────────────────
    // Tags the radio option whose label text is "MAX RANDOM" with a marker
    // class so CSS can attach a hover-revealed gif. Retried because Gradio
    // renders the Radio after first paint, and re-renders after some events.
    function _slurmTagMaxRandom() {
        var labels = document.querySelectorAll('label');
        var any = false;
        for (var i = 0; i < labels.length; i++) {
            var lbl = labels[i];
            if (lbl.classList.contains('slurm-max-option')) { any = true; continue; }
            // Match by direct text content trimmed — Gradio puts the option
            // text directly inside the <label>, alongside the <input>.
            var t = (lbl.textContent || '').trim();
            if (t === 'MAX RANDOM') {
                lbl.classList.add('slurm-max-option');
                any = true;
                _dbg('MAX RANDOM label tagged');
            }
        }
        return any;
    }
    var _maxTries = 0;
    var _maxIv = setInterval(function () {
        _slurmTagMaxRandom();
        if (++_maxTries > 80) clearInterval(_maxIv);  // ~20s of retries
    }, 250);

    // ── Beat mask chip strip ──────────────────────────────────────────────
    //
    // _slurmBuildBeatMask(resolution) renders N toggle-chip buttons into the
    // container div #slurm-beat-mask, where N is the number of note-subdivisions
    // per bar for the selected resolution:
    //
    //   1/1  → 1 chip   (one whole note = one bar)
    //   1/2  → 2 chips  (two half notes per bar)
    //   1/4  → 4 chips  (four quarter notes = beats 1–4)
    //   1/8  → 8 chips
    //   1/16 → 16 chips
    //
    // For 1/32, 1/64, 1/128, and MAX RANDOM the strip is hidden — the chip
    // count would be too dense (32+ per bar) and MAX RANDOM has no fixed grid.
    //
    // Each chip is a <button> that toggles between "on" (beat included) and
    // "off" (beat dropped from the output).  Clicking a chip updates the JS
    // global window._slurmBeatMask (a boolean array snapshot).  The Go
    // button's first chain step reads this global and passes it to Python via
    // Gradio's own output mechanism — NOT by writing to a DOM <textarea>.
    // (Writing to a Gradio 5 Svelte component's <textarea> from JS and
    // dispatching an 'input' event does NOT update Svelte's internal state,
    // so the textbox always reported "" to Python.  Using fn=None + outputs=
    // routes through Gradio's frontend→backend sync and is reliable.)
    //
    // All chips start "on" (all beats active) whenever the resolution changes
    // or the page first loads, so the default behaviour is unchanged.

    // _beatMask: current boolean array (index == note position in bar).
    // Chip clicks toggle entries.  The Go button's JS step reads this global
    // at fire-time via Gradio's own output path — much more reliable than
    // trying to update a Gradio Textbox's DOM value from outside the component
    // (which requires React's native-setter trick and breaks on Gradio 5's
    // Svelte runtime).
    var _beatMask = [];
    window._slurmBeatMask = _beatMask;   // expose immediately; updated on every change

    function _slurmBuildBeatMask(resolution) {
        var wrap = document.getElementById('slurm-beat-mask');
        if (!wrap) {
            _dbg('beat mask: #slurm-beat-mask container not found');
            return;
        }

        // Resolutions that have too many subdivisions to display a useful chip
        // strip, or that don't use a fixed beat grid.
        var hidden = (resolution === 'MAX RANDOM' ||
                      resolution === '1/32'       ||
                      resolution === '1/64'       ||
                      resolution === '1/128');
        if (hidden) {
            wrap.style.display = 'none';
            // Reset mask to "all on" so that switching back to a visible
            // resolution doesn't carry over a stale masked state.
            _beatMask.length = 0;
            window._slurmBeatMask = _beatMask;
            return;
        }

        // Map resolution string → number of chips.
        var countMap = { '1/1': 1, '1/2': 2, '1/4': 4, '1/8': 8, '1/16': 16 };
        var n = countMap[resolution] || 4;  // default 4 if something unexpected comes in

        // Always reset to all-on when resolution changes so the strip is fresh.
        _beatMask.length = 0;
        for (var k = 0; k < n; k++) _beatMask.push(true);
        window._slurmBeatMask = _beatMask.slice();   // expose a snapshot

        // Build the chip buttons.
        wrap.innerHTML = '';

        // Label above the strip.
        var lbl = document.createElement('div');
        lbl.className = 'slurm-beat-mask-label';
        lbl.textContent = 'beat mask · ' + resolution + ' · click to drop a beat';
        wrap.appendChild(lbl);

        // Chip row.
        var row = document.createElement('div');
        row.className = 'slurm-beat-mask-row';

        for (var i = 0; i < n; i++) {
            (function(idx) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'slurm-bar-chip slurm-bar-chip-on';
                // Beat numbering: 1-based with circled digit glyphs (① through ⑯).
                var circled = ['①','②','③','④',
                               '⑤','⑥','⑦','⑧',
                               '⑨','⑩','⑪','⑫',
                               '⑬','⑭','⑮','⑯'];
                btn.textContent = circled[idx] || (idx + 1);
                btn.title = 'beat ' + (idx + 1) + ' of ' + n
                          + ' (' + resolution + ') — click to toggle';

                btn.addEventListener('click', function() {
                    _beatMask[idx] = !_beatMask[idx];
                    window._slurmBeatMask = _beatMask.slice();   // update exposed snapshot
                    if (_beatMask[idx]) {
                        btn.className = 'slurm-bar-chip slurm-bar-chip-on';
                    } else {
                        btn.className = 'slurm-bar-chip slurm-bar-chip-off';
                    }
                    _dbg('beat mask: beat ' + (idx+1) + ' → ' + _beatMask[idx]
                         + '  mask=' + JSON.stringify(window._slurmBeatMask));
                });
                row.appendChild(btn);
            })(i);
        }

        wrap.appendChild(row);
        wrap.style.display = 'block';
        _dbg('beat mask: built ' + n + ' chips for resolution ' + resolution);
    }

    // Build the initial strip based on the default resolution (1/16).
    // Retry on a short poll because Gradio may not have rendered the container
    // div yet at the time this IIFE first runs.
    var _maskInitTries = 0;
    var _maskInitIv = setInterval(function() {
        var wrap = document.getElementById('slurm-beat-mask');
        if (wrap) {
            clearInterval(_maskInitIv);
            _slurmBuildBeatMask('1/16');   // matches the default resolution radio value
            _dbg('beat mask: initial strip built');
        }
        if (++_maskInitTries > 40) clearInterval(_maskInitIv);  // give up after ~10 s
    }, 250);

    // Expose so the resolution.change handler in slurm_ui.py can call it.
    window.slurmBuildBeatMask = _slurmBuildBeatMask;

    // ── Allow ANY file type on the audio input ────────────────────────────
    // Gradio's gr.Audio renders an <input type="file"> with accept="audio/*"
    // which causes the OS picker to filter out video/media files. We strip
    // the accept attribute so users can upload .mp4/.mov/.mkv etc. The
    // backend (librosa + audioread + ffmpeg) extracts audio transparently.
    function _slurmStripAccept() {
        var inputs = document.querySelectorAll('.slurm-audio input[type="file"]');
        for (var i = 0; i < inputs.length; i++) {
            if (inputs[i].dataset.slurmAcceptStripped) continue;
            inputs[i].removeAttribute('accept');
            inputs[i].dataset.slurmAcceptStripped = '1';
            _dbg('audio input accept= stripped (idx ' + i + ')');
        }
    }
    var _stripTries = 0;
    var _stripIv = setInterval(function () {
        _slurmStripAccept();
        if (++_stripTries > 80) clearInterval(_stripIv);
    }, 250);
})();
"""

# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM_CSS — Gradio UI stylesheet
# ───────────────────────────────────────────────────────────────────────────────
# Passed to gr.Blocks(css=CUSTOM_CSS) (or ui.launch depending on Gradio
# version).  Overrides Gradio's default light theme with the SIENA dark skin
# and adds all the custom component styles (chip-row radios, dark dropdowns,
# hover animations, Easter egg ::after pseudo-elements, etc.).
#
# WHY FIVE BLOCKS?
# The GIF Easter eggs are embedded directly in CSS background-image:url()
# rules using Python f-strings:
#
#   CUSTOM_CSS += f"""
#   .slurm-max-option::after {{
#       background-image: url("data:image/gif;base64,{_MAX_GIF_B64}");
#   }}
#   """
#
# Because of this, the GIF base64 variables must be defined BEFORE the CSS
# blocks that reference them.  That is why the GIF var definitions are
# interleaved with the CSS += blocks below — do not reorder them.
#
# Block map:
#   Block 1  (CUSTOM_CSS = """...""")   — core dark theme, layout, skins
#   _MAX_GIF_B64 defined here
#   Block 2  (CUSTOM_CSS += f"""...""") — Max hover animation
#   _BOB_GIF_B64 defined here
#   Block 3  (CUSTOM_CSS += f"""...""") — Bob hover animation
#   _HOBERMAN_GIF_B64 defined here
#   Block 4  (CUSTOM_CSS += f"""...""") — Hoberman-Max hover animation
#   _MAX_FIRE_GIF_B64 defined here
#   Block 5a (CUSTOM_CSS += f"""...""") — MaxFire beat-mask peek Easter egg
#   Block 5  (CUSTOM_CSS += """...""")  — compact chip-row controls
#   Block 6  (inside Block 5 closing)  — bar mask chip strip (.slurm-bar-chip-on/off)
# ═══════════════════════════════════════════════════════════════════════════════
CUSTOM_CSS = """
/* ═══════════════════════════════════════════════════════════════════════
   SIENA SLURMER — dark theme
   ═══════════════════════════════════════════════════════════════════════ */
:root {
    --slurm-bg:       #0e0c0c;
    --slurm-cyan:     #00b9e1;
    --slurm-orange:   #ffa600;
    --slurm-rose:     #a09090;
    --slurm-surface:  #161314;
    --slurm-surface2: #1e1a1b;
    --slurm-border:   #2a2323;
    --slurm-border-2: #342c2c;

    /* ── Gradio theme token overrides ─────────────────────────────────── */
    --body-text-color:                    #cdc6c6 !important;
    --body-text-color-subdued:            #7a7070 !important;
    --block-label-text-color:             #9a9090 !important;
    --block-info-text-color:              #6a6060 !important;
    --checkbox-label-text-color:          #cdc6c6 !important;
    --checkbox-label-text-color-selected: #cdc6c6 !important;
    --input-text-fill:                    #cdc6c6 !important;
    --slider-color:                       #00b9e1 !important;
    --background-fill-primary:            #161314 !important;
    --background-fill-secondary:          #0e0c0c !important;
    --border-color-primary:               #2a2323 !important;
    --border-color-accent:                #00b9e1 !important;
    --block-shadow:                       none !important;
    --block-border-width:                 1px !important;
    --block-radius:                       8px !important;
    --input-radius:                       6px !important;
    --container-radius:                   8px !important;
    --spacing-sm:                         6px !important;
    --spacing-md:                         10px !important;
    --spacing-lg:                         16px !important;
    --section-header-text-size:           0.72rem !important;
    --section-header-text-weight:         600 !important;
}

/* ── Page shell ────────────────────────────────────────────────────────── */
.gradio-container {
    background: #0e0c0c !important;
    font-family: "JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace !important;
    max-width: 1100px !important;
    padding: 20px 24px 40px !important;
}
footer { display: none !important; }

/* ── Header ────────────────────────────────────────────────────────────── */
.slurm-header {
    display: flex;
    align-items: center;
    gap: 18px;
    margin-bottom: 0.2rem;
}
.slurm-icon {
    width: 56px;
    height: 56px;
    border-radius: 12px;
    flex-shrink: 0;
    opacity: 0.92;
}
/* Header link wrappers — both the cat icon and the SIENA SLURMER title
   wrap into <a href="https://www.subvoyant.com" target="_blank">. Strip
   default anchor styling (no underline, inherit color/gradient) but keep
   cursor: pointer + subtle hover brightness so it's clearly clickable. */
.slurm-header-link,
.slurm-header-link:visited,
.slurm-header-link:active,
h1.slurm-title .slurm-header-link {
    text-decoration: none !important;
    color: inherit !important;
    background: none !important;
    -webkit-background-clip: text !important;
    background-clip: text !important;
    -webkit-text-fill-color: inherit !important;
    cursor: pointer;
    display: inline-block;
    transition: opacity 0.15s ease, filter 0.15s ease;
}
/* Keep the title's gradient text trick when the title is wrapped in <a> */
h1.slurm-title .slurm-header-link {
    background: linear-gradient(90deg, #00b9e1 0%, #ffa600 100%) !important;
    -webkit-background-clip: text !important;
    background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
}
.slurm-header-link:hover { opacity: 1; filter: brightness(1.15); }
.slurm-header-link:hover .slurm-icon { opacity: 1; }
.slurm-header-text { display: flex; flex-direction: column; }
h1.slurm-title {
    font-size: 2.6rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    background: linear-gradient(90deg, #00b9e1 0%, #ffa600 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 0.1em 0;
    line-height: 1;
}
.slurm-tag {
    color: #4e4646;
    font-size: 0.7rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 0;
}
/* subtitle markdown */
.gradio-container > .main > .wrap > .gap > p,
.gradio-container p {
    color: #5a5252 !important;
    font-size: 0.78rem !important;
    margin: 0 0 1rem 0 !important;
}
.gradio-container p strong { color: #7a7070 !important; font-weight: 600 !important; }

/* ── Blocks / panels ───────────────────────────────────────────────────── */
.gradio-container .block,
.gradio-container .gr-block,
.gradio-container fieldset {
    background: #161314 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    padding: 10px 12px !important;
}
/* tighten gap between stacked form controls */
.gradio-container .gap,
.gradio-container .form {
    gap: 8px !important;
}

/* ── Audio player ──────────────────────────────────────────────────────── */
/* Make waveform container dark and fix the scrollbar/timestamp overlap */
.gradio-container .waveform-container,
.gradio-container [class*="waveform"] {
    background: #0e0c0c !important;
    border-radius: 6px !important;
}
/* Fix scrollbar sitting on top of timestamps:
   hide the horizontal scrollbar inside the waveform scroll area */
.gradio-container .waveform-container > div,
.gradio-container [class*="waveform"] > div {
    scrollbar-width: none !important;        /* Firefox */
    -ms-overflow-style: none !important;     /* IE/Edge */
}
.gradio-container .waveform-container > div::-webkit-scrollbar,
.gradio-container [class*="waveform"] > div::-webkit-scrollbar {
    display: none !important;
}
/* Timestamp row — lift above any overflow */
.gradio-container .timestamps,
.gradio-container [class*="timestamps"] {
    position: relative !important;
    z-index: 2 !important;
    color: #4e4646 !important;
    font-size: 0.7rem !important;
    padding: 2px 0 0 0 !important;
}
/* Audio block label */
.gradio-container .block > .label-wrap span {
    font-size: 0.7rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #4e4646 !important;
}

/* ── Sliders ───────────────────────────────────────────────────────────── */
.gradio-container input[type="range"] {
    accent-color: #00b9e1;
    height: 3px !important;
}
/* Label + info for sliders/checkboxes */
.gradio-container .label-wrap > span { font-size: 0.75rem !important; }
.gradio-container .info,
.gradio-container [class*="info"] { font-size: 0.67rem !important; color: #4e4646 !important; }

/* ── Text inputs / dropdowns ───────────────────────────────────────────── */
.gradio-container input[type="number"],
.gradio-container input[type="text"],
.gradio-container textarea,
.gradio-container select {
    background: #0e0c0c !important;
    color: #cdc6c6 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 5px !important;
    font-size: 0.8rem !important;
    padding: 4px 8px !important;
}
.gradio-container select option {
    background: #161314 !important;
    color: #cdc6c6 !important;
}

/* ── In/Out bar ────────────────────────────────────────────────────────── */
#slurm-inout-bar {
    background: #0f0d0d !important;
    border: 1px solid #2a2323 !important;
    border-radius: 6px !important;
    padding: 4px 8px !important;
    margin: 4px 0 !important;
    display: flex !important;
    flex-wrap: nowrap !important;
    gap: 5px !important;
    align-items: center !important;
}
#slurm-inout-bar > div { flex-shrink: 0; }
#slurm-clock-wrap {
    color: #00b9e1;
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.88rem;
    letter-spacing: 0.05em;
    min-width: 84px;
    padding: 0 2px;
}
.slurm-io-btn,
.slurm-io-btn > .wrap,
.slurm-io-btn button {
    background: transparent !important;
    color: #5a5252 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    font-family: "JetBrains Mono", ui-monospace, monospace !important;
    font-size: 0.72rem !important;
    padding: 1px 8px !important;
    min-width: unset !important;
    min-height: unset !important;
    height: auto !important;
    line-height: 1.7 !important;
    transition: color 0.15s, border-color 0.15s !important;
}
.slurm-io-btn button:hover {
    background: transparent !important;
    color: #cdc6c6 !important;
    border-color: #00b9e1 !important;
}
.slurm-io-clear button { color: #4a4040 !important; }
.slurm-io-clear button:hover {
    color: #ffa600 !important;
    border-color: #ffa600 !important;
}

/* ── Compact text inputs — unified typography ─────────────────────────── */
/* The in/out sec boxes and the seed textbox all share the same compact
   single-line look, matching the base font-size (0.8rem) so they're
   typographically consistent with every other text input in the app.
   Gradio renders Textbox labels TWO ways depending on whether info= is
   set: bare <label> when info is absent (browser default size, large),
   vs <div class="label-wrap"><span> when info is present (smaller).
   We force both patterns to look identical so labels stay consistent
   regardless of whether the component has an info subtitle. */
#start-sec-box, #end-sec-box, #slurm-seed-box {
    min-height: unset !important;
}
#start-sec-box input, #end-sec-box input,
#start-sec-box textarea, #end-sec-box textarea,
#slurm-seed-box input, #slurm-seed-box textarea {
    font-size: 0.8rem !important;
    padding: 3px 8px !important;
    line-height: 1.5 !important;
    min-height: unset !important;
    height: auto !important;
}
/* Force label-rendering consistency across BOTH info-present and info-absent
   Textbox patterns. Catch every label/wrap variant Gradio might render. */
#start-sec-box label, #start-sec-box .label-wrap > span,
#start-sec-box .label-wrap span,
#end-sec-box label, #end-sec-box .label-wrap > span,
#end-sec-box .label-wrap span,
#slurm-seed-box label, #slurm-seed-box .label-wrap > span,
#slurm-seed-box .label-wrap span {
    font-size: 0.75rem !important;
    font-weight: 400 !important;
    color: #9a9090 !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    line-height: 1.4 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Pin in/out input boxes to a consistent baseline. Even with matching info=
   on both, Gradio's internal label-wrap padding can differ by a few pixels,
   pushing the input boxes to slightly different y-positions. Forcing the
   container to flex-column with content aligned at the BOTTOM ensures the
   inputs land on the same baseline regardless of what's above them. */
#start-sec-box, #end-sec-box {
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-end !important;
    min-height: 78px !important;
}
#start-sec-box > *, #end-sec-box > * {
    flex-shrink: 0 !important;
}
/* Also tighten the info subtitle vertical rhythm for both, so neither
   adds extra space between info and input. */
#start-sec-box .info, #end-sec-box .info,
#start-sec-box [class*="info"], #end-sec-box [class*="info"] {
    margin: 0 !important;
    padding: 0 !important;
    line-height: 1.3 !important;
}

/* ── Neutralize Gradio's :focus-within block highlight ────────────────── */
/* By default, Gradio recolors a block's border AND label to the accent
   color (cyan, in our theme) when any input inside it has focus. Result:
   "in (sec)" looks dramatically different from "out (sec)" depending on
   which one was last clicked — not a setting on the component, just
   default focus-within behavior. We keep the block visually identical
   regardless of focus; the input itself still shows a cursor so users
   know where they're typing. */
.gradio-container .block:focus-within,
.gradio-container .gr-block:focus-within,
.gradio-container fieldset:focus-within,
#start-sec-box:focus-within,
#end-sec-box:focus-within,
#slurm-seed-box:focus-within {
    border-color: #2a2323 !important;
    background: #161314 !important;
    box-shadow: none !important;
}
.gradio-container .block:focus-within .label-wrap > span,
.gradio-container .block:focus-within > .label-wrap span,
.gradio-container .block:focus-within label,
#start-sec-box:focus-within .label-wrap > span,
#end-sec-box:focus-within .label-wrap > span,
#slurm-seed-box:focus-within .label-wrap > span {
    color: #9a9090 !important;  /* same as --block-label-text-color */
}
/* Keep input focus subtle but visible (1px brighter inner border) */
#start-sec-box input:focus, #end-sec-box input:focus,
#slurm-seed-box input:focus, #start-sec-box textarea:focus,
#end-sec-box textarea:focus, #slurm-seed-box textarea:focus {
    outline: none !important;
    border-color: #3a3333 !important;
}

/* ── Primary (slurmify) button ─────────────────────────────────────────── */
.gradio-container button.primary,
.gradio-container button[variant="primary"] {
    background: #00b9e1 !important;
    color: #0a0808 !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    font-size: 0.9rem !important;
    transition: filter 0.15s !important;
}
.gradio-container button.primary:hover,
.gradio-container button[variant="primary"]:hover {
    filter: brightness(1.12) !important;
}
/* quit button */
.gradio-container button.stop,
.gradio-container button[variant="stop"] {
    background: transparent !important;
    border: 1px solid #2a2323 !important;
    color: #5a5252 !important;
    font-size: 0.72rem !important;
    border-radius: 6px !important;
}
.gradio-container button.stop:hover,
.gradio-container button[variant="stop"]:hover {
    border-color: #6a3030 !important;
    color: #b06060 !important;
}

/* ── FX accordion panel ────────────────────────────────────────────────── */
#slurm-fx-panel > .label-wrap span,
#slurm-fx-panel > .block-label span {
    color: #00b9e1 !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
}
#slurm-fx-panel .block {
    background: #0f0d0d !important;
    border: 1px solid #231f1f !important;
}
/* FX section headings inside accordion */
.slurm-fx-section {
    color: #4e4646;
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding: 2px 0 4px 0;
    border-bottom: 1px solid #231f1f;
    margin-bottom: 2px;
}
/* Burn button */
#slurm-burn-btn button {
    background: linear-gradient(90deg, #00b9e1 0%, #0099c8 100%) !important;
    color: #080707 !important;
    border: none !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em !important;
    font-size: 0.82rem !important;
    border-radius: 6px !important;
}
#slurm-burn-btn button:hover {
    filter: brightness(1.15) !important;
}

/* ── Dancer / loading gif ──────────────────────────────────────────────── */
#siena-dancer {
    display: flex;
    justify-content: center;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
#siena-dancer img { max-width: 180px; }

/* ═══════════════════════════════════════════════════════════════════════
   Skin picker (visible in all skins, restyled per-skin below)
   ═══════════════════════════════════════════════════════════════════════ */
.slurm-skin-wrap {
    margin-left: auto;
    display: flex; align-items: center; gap: 6px;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #6a6060;
}
.slurm-skin-wrap select {
    background: #161314; color: #cdc6c6;
    border: 1px solid #2a2323; border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.7rem;
    font-family: inherit;
}

/* ═══════════════════════════════════════════════════════════════════════
   Audio-reactive elements — hidden by default, made visible per-skin.
   ═══════════════════════════════════════════════════════════════════════ */
#slurm-vu-meter, #slurm-go-halo {
    display: none;
}

/* ═══════════════════════════════════════════════════════════════════════
   Compact controls — default-skin only.
   The browser-default slider thumb is ~16-20 px and feels oversized
   against our slim 3 px tracks; we explicitly draw it at 12 px and
   tighten the block / gap / padding rhythm. Type sizes are untouched
   because the labels and value readouts are already at a good size.
   The Acid and Hardware skins reach into the slider machinery with
   higher-specificity selectors and override these intentionally.
   ═══════════════════════════════════════════════════════════════════════ */
:root[data-skin="default"] .gradio-container .block,
:root[data-skin="default"] .gradio-container .gr-block,
:root[data-skin="default"] .gradio-container fieldset,
body[data-skin="default"] .gradio-container .block,
body[data-skin="default"] .gradio-container .gr-block,
body[data-skin="default"] .gradio-container fieldset {
    padding: 6px 10px !important;       /* was 10px 12px */
}
body[data-skin="default"] .gradio-container .gap,
body[data-skin="default"] .gradio-container .form {
    gap: 5px !important;                /* was 8px */
}
body[data-skin="default"] .gradio-container .block > .label-wrap {
    margin-bottom: 1px !important;
}
body[data-skin="default"] .gradio-container .info,
body[data-skin="default"] .gradio-container [class*="info"] {
    margin-top: 0 !important;
    line-height: 1.2 !important;
}

/* Smaller, explicitly-styled slider thumbs (default skin) */
body[data-skin="default"] .gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #00b9e1;
    border: 2px solid #0e0c0c;
    box-shadow: 0 0 0 1px #2a2323;
    margin-top: -4.5px;       /* (12px thumb - 3px track) / 2, fudged to center */
    cursor: grab;
}
body[data-skin="default"] .gradio-container input[type="range"]::-moz-range-thumb {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #00b9e1;
    border: 2px solid #0e0c0c;
    box-shadow: 0 0 0 1px #2a2323;
    cursor: grab;
}

/* Tighter inputs / dropdowns / numeric boxes (default skin) */
body[data-skin="default"] .gradio-container input[type="number"],
body[data-skin="default"] .gradio-container input[type="text"],
body[data-skin="default"] .gradio-container textarea,
body[data-skin="default"] .gradio-container select {
    padding: 3px 7px !important;       /* was 4px 8px */
    min-height: unset !important;
}

/* Tighter buttons (default skin) — but the primary slurmify button stays
   visually substantial because it's the action target. */
body[data-skin="default"] .gradio-container button {
    padding: 5px 12px !important;
    min-height: unset !important;
}
body[data-skin="default"] .gradio-container button.primary,
body[data-skin="default"] .gradio-container button[variant="primary"] {
    padding: 9px 16px !important;
}

/* ═══════════════════════════════════════════════════════════════════════
   SKIN: ACID CATHEDRAL  (body[data-skin="acid"])
   Trippy / liquid / audio-reactive. Glassmorphic accordions, animated
   rainbow title, slow hue-rotation on background, glowing slider thumbs.
   ═══════════════════════════════════════════════════════════════════════ */
@keyframes slurm-acid-drift {
    0%   { background-position:   0% 50%, 100% 50%, 50% 0%;   filter: hue-rotate(0deg);   }
    50%  { background-position: 100% 50%,   0% 50%, 50% 100%; filter: hue-rotate(180deg); }
    100% { background-position:   0% 50%, 100% 50%, 50% 0%;   filter: hue-rotate(360deg); }
}
@keyframes slurm-acid-text {
    0%   { background-position:   0% 50%; }
    100% { background-position: 200% 50%; }
}
@keyframes slurm-acid-pulse {
    0%, 100% { box-shadow: 0 0 30px 6px rgba(180, 60, 230, 0.55),
                           0 0 80px 20px rgba(60, 200, 255, 0.35); }
    50%      { box-shadow: 0 0 60px 14px rgba(255, 80, 220, 0.7),
                           0 0 140px 32px rgba(120, 220, 255, 0.5); }
}

body[data-skin="acid"] .gradio-container {
    background:
        radial-gradient(ellipse at 20% 30%, #ff3eb1 0%, transparent 55%),
        radial-gradient(ellipse at 80% 60%, #2bd4ff 0%, transparent 55%),
        radial-gradient(ellipse at 50% 90%, #b07cff 0%, transparent 60%),
        #1a0824 !important;
    background-size: 200% 200%, 200% 200%, 200% 200%, 100% 100%;
    animation: slurm-acid-drift 28s linear infinite;
    color: #fff !important;
}
body[data-skin="acid"] {
    background: #1a0824 !important;
}

/* Title — chunky display font with animated rainbow background-clip */
body[data-skin="acid"] .slurm-title {
    font-family: 'Bagel Fat One', 'Inter', system-ui, sans-serif !important;
    font-size: 3.4rem !important;
    font-weight: 400 !important;
    letter-spacing: -0.02em !important;
    background: linear-gradient(90deg,
        #ff3eb1, #ffea00, #2bd4ff, #b07cff, #ff3eb1) !important;
    background-size: 200% auto !important;
    -webkit-background-clip: text !important;
            background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    color: transparent !important;
    animation: slurm-acid-text 6s linear infinite;
    text-shadow: 0 2px 30px rgba(255, 60, 180, 0.4) !important;
}
body[data-skin="acid"] .slurm-tag {
    color: rgba(255, 255, 255, 0.7) !important;
    letter-spacing: 0.18em !important;
}
body[data-skin="acid"] .slurm-icon {
    filter: drop-shadow(0 0 12px rgba(255, 200, 255, 0.6))
            drop-shadow(0 0 4px rgba(180, 100, 255, 0.9)) !important;
}

/* Glassmorphic accordions and blocks */
body[data-skin="acid"] .gradio-container .block,
body[data-skin="acid"] .gradio-container fieldset,
body[data-skin="acid"] #slurm-fx-panel,
body[data-skin="acid"] #slurm-video-panel {
    background: rgba(25, 10, 40, 0.35) !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
    backdrop-filter: blur(18px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(18px) saturate(180%) !important;
    border-radius: 14px !important;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.4),
                inset 0 0 1px rgba(255, 255, 255, 0.4) !important;
}
body[data-skin="acid"] .gradio-container .label-wrap span,
body[data-skin="acid"] .gradio-container .block > label,
body[data-skin="acid"] .gradio-container input,
body[data-skin="acid"] .gradio-container textarea,
body[data-skin="acid"] .gradio-container select {
    color: #fff !important;
}
body[data-skin="acid"] .gradio-container .info,
body[data-skin="acid"] .gradio-container [class*="info"] {
    color: rgba(255, 255, 255, 0.55) !important;
}
body[data-skin="acid"] .gradio-container input[type="text"],
body[data-skin="acid"] .gradio-container input[type="number"],
body[data-skin="acid"] .gradio-container textarea {
    background: rgba(0, 0, 0, 0.3) !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
}

/* Sliders — glowing thumbs, gradient tracks (smaller than v1) */
body[data-skin="acid"] .gradio-container input[type="range"]::-webkit-slider-runnable-track {
    background: linear-gradient(90deg, #ff3eb1, #2bd4ff, #b07cff) !important;
    height: 4px !important; border-radius: 2px !important;
}
body[data-skin="acid"] .gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: #fff !important;
    border: 2px solid #ff3eb1 !important;
    margin-top: -5px;
    box-shadow: 0 0 10px 2px rgba(255, 100, 220, 0.75),
                0 0 26px 6px rgba(60, 200, 255, 0.35) !important;
    cursor: grab;
}
body[data-skin="acid"] .gradio-container input[type="range"]::-moz-range-thumb {
    width: 14px; height: 14px;
    border-radius: 50%;
    background: #fff !important;
    border: 2px solid #ff3eb1 !important;
    box-shadow: 0 0 10px 2px rgba(255, 100, 220, 0.75),
                0 0 26px 6px rgba(60, 200, 255, 0.35) !important;
    cursor: grab;
}
/* Compact block padding for acid skin too */
body[data-skin="acid"] .gradio-container .block,
body[data-skin="acid"] .gradio-container fieldset {
    padding: 6px 10px !important;
}
body[data-skin="acid"] .gradio-container .gap,
body[data-skin="acid"] .gradio-container .form {
    gap: 5px !important;
}

/* Buttons — primary slurmify gets the full glow treatment */
body[data-skin="acid"] .gradio-container button.primary,
body[data-skin="acid"] .gradio-container button[variant="primary"] {
    background: linear-gradient(90deg, #ff3eb1, #b07cff, #2bd4ff) !important;
    background-size: 200% auto !important;
    color: #fff !important;
    border: 1px solid rgba(255, 255, 255, 0.35) !important;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5) !important;
    box-shadow: 0 0 24px rgba(255, 100, 220, 0.45) !important;
    animation: slurm-acid-text 4s linear infinite;
}
body[data-skin="acid"] .gradio-container button.primary:hover,
body[data-skin="acid"] .gradio-container button[variant="primary"]:hover {
    box-shadow: 0 0 36px 4px rgba(255, 100, 220, 0.65) !important;
    filter: brightness(1.18) !important;
}

/* The dancer rides above the shader-y background */
body[data-skin="acid"] #siena-dancer img {
    mix-blend-mode: screen !important;
    filter: hue-rotate(0deg) saturate(1.4) !important;
}

/* Halo around the slurmify button — audio-reactive (set by JS) */
body[data-skin="acid"] #slurm-go-halo {
    display: block !important;
    position: relative;
    border-radius: 16px;
    padding: 0;
    margin: 6px 0;
    pointer-events: none;
    height: 0;
}

/* Skin picker on acid */
body[data-skin="acid"] .slurm-skin-wrap { color: rgba(255, 255, 255, 0.7); }
body[data-skin="acid"] .slurm-skin-wrap select {
    background: rgba(0, 0, 0, 0.3) !important;
    border: 1px solid rgba(255, 255, 255, 0.3) !important;
    color: #fff !important;
}

/* ═══════════════════════════════════════════════════════════════════════
   SKIN: HARDWARE RACK  (body[data-skin="hardware"])
   Brushed metal panels, recessed knurled knobs, LCD readouts, big LEDs.
   ═══════════════════════════════════════════════════════════════════════ */
body[data-skin="hardware"] {
    background:
        repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.025) 0px,
            rgba(0,0,0,0)   1px,
            rgba(0,0,0,0.04) 2px,
            rgba(0,0,0,0)   3px),
        linear-gradient(180deg, #2a2826 0%, #1d1c1a 50%, #232120 100%) !important;
    color: #d8d2c0 !important;
}
body[data-skin="hardware"] .gradio-container {
    background: transparent !important;
    color: #d8d2c0 !important;
}

/* Title — vintage rack-mount feel */
body[data-skin="hardware"] .slurm-title {
    font-family: 'Major Mono Display', 'Share Tech Mono', monospace !important;
    font-size: 2.2rem !important;
    color: #f4ecd0 !important;
    letter-spacing: 0.12em !important;
    text-shadow:
        0 1px 0 rgba(255, 255, 255, 0.18),
        0 -1px 0 rgba(0, 0, 0, 0.6),
        0 0 18px rgba(255, 220, 160, 0.15) !important;
}
body[data-skin="hardware"] .slurm-tag {
    font-family: 'Share Tech Mono', monospace !important;
    color: #948c78 !important;
    letter-spacing: 0.15em !important;
    font-size: 0.66rem !important;
}

/* Brushed-metal panels around blocks/accordions */
body[data-skin="hardware"] .gradio-container .block,
body[data-skin="hardware"] .gradio-container fieldset,
body[data-skin="hardware"] #slurm-fx-panel,
body[data-skin="hardware"] #slurm-video-panel {
    background:
        repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.02) 0px,
            rgba(0,0,0,0)   1px,
            rgba(0,0,0,0.06) 2px,
            rgba(0,0,0,0)   3px),
        linear-gradient(180deg, #3a3631 0%, #2a2724 50%, #353027 100%) !important;
    border: 1px solid #1a1614 !important;
    border-radius: 8px !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 235, 200, 0.08),
        inset 0 -1px 0 rgba(0, 0, 0, 0.6),
        0 2px 6px rgba(0, 0, 0, 0.6) !important;
    /* Faux corner screws */
    position: relative;
}
body[data-skin="hardware"] .gradio-container .block::before,
body[data-skin="hardware"] .gradio-container .block::after,
body[data-skin="hardware"] #slurm-fx-panel::before,
body[data-skin="hardware"] #slurm-fx-panel::after {
    content: "";
    position: absolute;
    width: 10px; height: 10px;
    border-radius: 50%;
    background:
        radial-gradient(circle at 35% 35%,
            #d6cfb8 0%, #807866 45%, #1a1612 90%);
    box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.6),
                0 0 1px rgba(0, 0, 0, 0.6);
    pointer-events: none;
    z-index: 2;
}
body[data-skin="hardware"] .gradio-container .block::before { top: 6px; left: 6px; }
body[data-skin="hardware"] .gradio-container .block::after  { top: 6px; right: 6px; }

/* Section headings — engraved label feel */
body[data-skin="hardware"] .slurm-fx-section,
body[data-skin="hardware"] .gradio-container .label-wrap span,
body[data-skin="hardware"] .gradio-container .block > label {
    font-family: 'Major Mono Display', monospace !important;
    color: #f4ecd0 !important;
    text-shadow: 0 1px 0 rgba(0, 0, 0, 0.7),
                 0 -1px 0 rgba(255, 235, 200, 0.06) !important;
    letter-spacing: 0.12em !important;
}
body[data-skin="hardware"] .gradio-container .info,
body[data-skin="hardware"] .gradio-container [class*="info"] {
    font-family: 'Share Tech Mono', monospace !important;
    color: #948c78 !important;
}

/* Recessed slider grooves with knurled chrome thumbs */
body[data-skin="hardware"] .gradio-container input[type="range"] {
    height: 28px;
}
body[data-skin="hardware"] .gradio-container input[type="range"]::-webkit-slider-runnable-track {
    background: linear-gradient(180deg, #100e0c 0%, #1f1c19 50%, #100e0c 100%) !important;
    height: 8px !important;
    border-radius: 4px !important;
    box-shadow:
        inset 0 1px 2px rgba(0, 0, 0, 0.9),
        inset 0 -1px 0 rgba(255, 235, 200, 0.05) !important;
    border: 1px solid #0c0a08 !important;
}
body[data-skin="hardware"] .gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 24px; height: 24px;
    margin-top: -9px;
    border-radius: 50%;
    background:
        repeating-conic-gradient(from 0deg,
            #d6cfb8 0deg, #b8b09a 8deg,
            #d6cfb8 16deg, #807866 24deg),
        radial-gradient(circle at 35% 35%, #f4ecd0, #807866) !important;
    border: 1px solid #1a1612 !important;
    box-shadow:
        0 2px 4px rgba(0, 0, 0, 0.7),
        inset 0 1px 0 rgba(255, 255, 255, 0.4),
        inset 0 -2px 4px rgba(0, 0, 0, 0.5) !important;
    cursor: grab;
}

/* Numeric readouts — LCD-amber on smoked glass */
body[data-skin="hardware"] .gradio-container input[type="number"],
body[data-skin="hardware"] .gradio-container input[type="text"],
body[data-skin="hardware"] .gradio-container textarea {
    background: #0a0805 !important;
    color: #ffb74d !important;
    font-family: 'VT323', 'Share Tech Mono', monospace !important;
    font-size: 1rem !important;
    border: 1px solid #0c0a08 !important;
    border-radius: 3px !important;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.9),
                inset 0 0 8px rgba(255, 150, 60, 0.08) !important;
    text-shadow: 0 0 6px rgba(255, 150, 60, 0.6) !important;
    letter-spacing: 0.05em !important;
}

/* Buttons — engraved metal */
body[data-skin="hardware"] .gradio-container button.primary,
body[data-skin="hardware"] .gradio-container button[variant="primary"],
body[data-skin="hardware"] #slurm-burn-btn button,
body[data-skin="hardware"] #slurm-video-btn button {
    background: linear-gradient(180deg, #c9c1a8 0%, #a89e83 50%, #877e63 100%) !important;
    color: #1a1612 !important;
    font-family: 'Major Mono Display', monospace !important;
    letter-spacing: 0.1em !important;
    border: 1px solid #1a1612 !important;
    border-radius: 4px !important;
    text-shadow: 0 1px 0 rgba(255, 235, 200, 0.4) !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.5),
        inset 0 -1px 0 rgba(0, 0, 0, 0.3),
        0 2px 4px rgba(0, 0, 0, 0.5) !important;
}
body[data-skin="hardware"] .gradio-container button.primary:hover {
    filter: brightness(1.08);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.6),
        inset 0 -1px 0 rgba(0, 0, 0, 0.3),
        0 2px 8px rgba(255, 150, 60, 0.3) !important;
}

/* LED indicator next to the checkboxes — JS sets data-on per state */
body[data-skin="hardware"] input[type="checkbox"] {
    appearance: none; -webkit-appearance: none;
    width: 16px; height: 16px;
    border-radius: 50%;
    background:
        radial-gradient(circle at 35% 35%, #4a1a1a 0%, #2a0a0a 70%, #100404 100%) !important;
    border: 1px solid #1a1612 !important;
    box-shadow:
        inset 0 1px 2px rgba(0, 0, 0, 0.9),
        0 0 0 2px #2a2826 !important;
    cursor: pointer;
    position: relative;
}
body[data-skin="hardware"] input[type="checkbox"]:checked {
    background:
        radial-gradient(circle at 35% 35%, #ff5050 0%, #ff1010 50%, #b00808 100%) !important;
    box-shadow:
        inset 0 1px 2px rgba(255, 200, 200, 0.4),
        0 0 12px 2px rgba(255, 60, 60, 0.7),
        0 0 0 2px #2a2826 !important;
}

/* VU meter visible only here */
body[data-skin="hardware"] #slurm-vu-meter {
    display: block !important;
    width: 100%;
    height: 28px;
    margin: 6px 0 0 0;
    background:
        linear-gradient(180deg, #100e0c 0%, #1f1c19 50%, #100e0c 100%) !important;
    border: 1px solid #0c0a08 !important;
    border-radius: 4px !important;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.8) !important;
}

/* Skin picker on hardware */
body[data-skin="hardware"] .slurm-skin-wrap {
    color: #948c78;
    font-family: 'Major Mono Display', monospace;
}
body[data-skin="hardware"] .slurm-skin-wrap select {
    background: #0a0805 !important;
    color: #ffb74d !important;
    border: 1px solid #1a1612 !important;
    font-family: 'Share Tech Mono', monospace !important;
}
"""

# ── _MAX_GIF_B64 ──────────────────────────────────────────────────────────────
# Max the tester's face as a base64-encoded GIF (~2.5 KB).
# Inlining avoids an extra HTTP request on page load and sidesteps the
# _asset() path resolution needed for PyInstaller-bundled files.
# This var is referenced in CUSTOM_CSS Block 2 immediately below, so it
# MUST be defined here — do not move it below the CSS += block.
# ─────────────────────────────────────────────────────────────────────────────
_MAX_GIF_B64 = "R0lGODlhUgBvAKIHADwpHdfX1tKrjamGZ+3Jr7O5rmxVRf///yH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDI3LjYgKE1hY2ludG9zaCkiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6NjE2RTM1MDczRkUxMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6NjE2RTM1MDgzRkUxMTFGMUJGNERFNUMxMUQ0RTFFRUMiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDo2MTZFMzUwNTNGRTExMUYxQkY0REU1QzExRDRFMUVFQyIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDo2MTZFMzUwNjNGRTExMUYxQkY0REU1QzExRDRFMUVFQyIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PgH//v38+/r5+Pf29fTz8vHw7+7t7Ovq6ejn5uXk4+Lh4N/e3dzb2tnY19bV1NPS0dDPzs3My8rJyMfGxcTD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"

CUSTOM_CSS += f"""
/* MAX RANDOM hover gif — tagged by INIT_JS as .slurm-max-option */
.slurm-max-option {{
    position: relative;
    overflow: visible !important;
}}
.slurm-max-option::after {{
    content: "";
    position: absolute;
    /* MAX RANDOM is the last radio option — right of it is empty space, so
       positioning the gif there avoids any overflow:hidden ancestor clipping. */
    left: calc(100% + 12px);
    bottom: -12px;
    transform: translateX(-12px) scale(0.55);
    transform-origin: left bottom;
    width: 110px;
    height: 149px;
    background-image: url("data:image/gif;base64,{_MAX_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.18s ease, transform 0.18s ease;
    z-index: 9999;
    filter: drop-shadow(0 6px 14px rgba(0,0,0,0.55));
}}
.slurm-max-option:hover::after {{
    opacity: 1;
    transform: translateX(0) scale(1);
}}
"""

# ── _BOB_GIF_B64 ──────────────────────────────────────────────────────────────
# Bob's face as a base64-encoded GIF.  Bob suggested the "reveal temp files"
# feature, so the 📁 button gets Bob as its hover Easter egg.
# Portrait orientation (99 × 361) — slides up from below the button.
# Referenced in CUSTOM_CSS Block 3 immediately below.
# ─────────────────────────────────────────────────────────────────────────────
_BOB_GIF_B64 = "R0lGODlhYwBpAaIHAF9UTMCzqQq7NvwFORkZwe2GADw7NgAAACH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDIwMjYgTWFjaW50b3NoIiB4bXBNTTpJbnN0YW5jZUlEPSJ4bXAuaWlkOjU5MUJDRDVDNDAwQTExRjFCRjRERTVDMTFENEUxRUVDIiB4bXBNTTpEb2N1bWVudElEPSJ4bXAuZGlkOjU5MUJDRDVENDAwQTExRjFCRjRERTVDMTFENEUxRUVDIj4gPHhtcE1NOkRlcml2ZWRGcm9tIHN0UmVmOmluc3RhbmNlSUQ9InhtcC5paWQ6NTkxQkNENUE0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHN0UmVmOmRvY3VtZW50SUQ9InhtcC5kaWQ6NTkxQkNENUI0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiLz4gPC9yZGY6RGVzY3JpcHRpb24+IDwvcmRmOlJERj4gPC94OnhtcG1ldGE+IDw/eHBhY2tldCBlbmQ9InIiPz4B//79/Pv6+fj39vX08/Lx8O/u7ezr6uno5+bl5OPi4eDf3t3c29rZ2NfW1dTT0tHQz87NzMvKycjHxsXEw8LB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"

CUSTOM_CSS += f"""
/* Bob hover gif — applied to the reveal-temp-files button via
   elem_classes=["slurm-bob-option"]. Tall portrait sized to
   ~75x274 (preserves the 99:361 aspect ratio of the source). */
.slurm-bob-option {{
    position: relative;
    overflow: visible !important;
}}
.slurm-bob-option::after {{
    content: "";
    position: absolute;
    /* Anchor at the BOTTOM edge of the button so Bob springs UPWARD
       from the button itself. The translateY(20px) start-state hides
       him just below — he then slides up + scales in on hover. */
    bottom: 0;
    left: 50%;
    transform: translateX(-50%) translateY(20px) scale(0.6);
    transform-origin: bottom center;
    width: 75px;
    height: 274px;
    background-image: url("data:image/gif;base64,{_BOB_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: bottom center;
    opacity: 0;
    pointer-events: none;
    /* Bouncy cubic-bezier (overshoot at the end) gives Bob the
       playful spring on his way up — befits an easter egg. */
    transition: opacity 0.18s ease,
                transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1);
    z-index: 9999;
    filter: drop-shadow(0 6px 16px rgba(0,0,0,0.55));
}}
.slurm-bob-option:hover::after {{
    opacity: 1;
    /* Final pose: anchored at button bottom, sprung fully up. */
    transform: translateX(-50%) translateY(0) scale(1);
}}
"""

# ── _HOBERMAN_GIF_B64 ─────────────────────────────────────────────────────────
# Hoberman-Max GIF — landscape (371 × 307) used as the 🎲 randomise-all button
# Easter egg.  Uses the same bottom-up spring animation as Bob's gif for visual
# consistency between the two utility buttons.
# Referenced in CUSTOM_CSS Block 4 immediately below.
# ─────────────────────────────────────────────────────────────────────────────
_HOBERMAN_GIF_B64 = "R0lGODlhcwEzAaIHAP8AAMRMPQEv3ADAF+ucHdeaYvzMJwAAACH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wTU09Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8iIHhtbG5zOnN0UmVmPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvc1R5cGUvUmVzb3VyY2VSZWYjIiB4bWxuczp4bXA9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8iIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6NTkxQkNENjE0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6NTkxQkNENjA0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDIwMjYgTWFjaW50b3NoIj4gPHhtcE1NOkRlcml2ZWRGcm9tIHN0UmVmOmluc3RhbmNlSUQ9IjI3RDA5OTdFMjg1QTU1NkJGOEM0ODJFQzlCMkQxM0RBIiBzdFJlZjpkb2N1bWVudElEPSIyN0QwOTk3RTI4NUE1NTZCRjhDNDgyRUM5QjJEMTNEQSIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PgH//v38+/r5+Pf29fTz8vHw7+7t7Ovq6ejn5uXk4+Lh4N/e3dzb2tnY19bV1NPS0dDPzs3My8rJyMfGxcTDwsHAv769vLu6ubi3trW0s7Kx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"

CUSTOM_CSS += f"""
/* Randomize-all popup — uses hobermanmax.gif (landscape) with Bob's
   bottom-up spring animation. */
.slurm-max-popup {{
    position: relative;
    overflow: visible !important;
}}
.slurm-max-popup::after {{
    content: "";
    position: absolute;
    /* Anchored at button bottom — rises straight up out of the button. */
    bottom: 0;
    left: 50%;
    transform: translateX(-50%) translateY(20px) scale(0.6);
    transform-origin: bottom center;
    /* Hoberman-Max source is 371x307 landscape — preserve aspect at display. */
    width: 145px;
    height: 120px;
    background-image: url("data:image/gif;base64,{_HOBERMAN_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: bottom center;
    opacity: 0;
    pointer-events: none;
    /* Same bouncy spring as Bob for matched motion. */
    transition: opacity 0.18s ease,
                transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1);
    z-index: 9999;
    filter: drop-shadow(0 6px 16px rgba(0,0,0,0.55));
}}
.slurm-max-popup:hover::after {{
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(1);
}}
"""

# ── _MAX_FIRE_GIF_B64 ────────────────────────────────────────────────────────
# MaxFire02.gif — Max raises up and comes back down (400×278 px, 19 frames).
# Easter egg on the beat mask chip strip: hover the panel and Max peeks up
# from behind it, as if checking on the beat grid.  No CSS spring animation
# is used — the GIF supplies its own rise-and-fall motion.  Displayed at
# 240×167 px (preserves the 400:278 source aspect ratio).  The ::after
# pseudo-element is anchored at bottom:100% so its bottom edge sits flush
# with the top of #slurm-beat-mask — Max appears to emerge from behind the
# panel.  Referenced in CUSTOM_CSS Block 5a immediately below.
# ─────────────────────────────────────────────────────────────────────────────
_MAX_FIRE_GIF_B64 = "R0lGODlhkAEWAaIFAD8jEvQVBvfj0p5vRvXIPP///wAAAAAAACH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDI3LjYgKE1hY2ludG9zaCkiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6NjU1NkJEMDM0MjU2MTFGMUFBNEJBRjNFRTQ1OEQ5NDgiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6NjU1NkJEMDQ0MjU2MTFGMUFBNEJBRjNFRTQ1OEQ5NDgiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDo2NTU2QkQwMTQyNTYxMUYxQUE0QkFGM0VFNDU4RDk0OCIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDo2NTU2QkQwMjQyNTYxMUYxQUE0QkFGM0VFNDU4RDk0OCIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PgH//v38+/r5+Pf29fTz8vHw7+7t7Ovq6ejn5uXk4+Lh4N/e3dzb2tnY19bV1NPS0dDPzs3My8rJyMfGxcTD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"

CUSTOM_CSS += f"""
/* Beat mask hover — MaxFire02 peek-up Easter egg.
   #slurm-beat-mask needs position:relative + overflow:visible so its
   ::after can extend above the panel without being clipped.  The GIF is
   400×278, self-animating (Max rises then falls back down); displayed at
   240×167 px with background-position:bottom-center so the GIF’s bottom
   frame aligns with the panel’s top edge — Max appears to emerge from
   behind the chip strip.  No CSS spring: the GIF carries its own motion. */
#slurm-beat-mask {{
    position: relative;
    overflow: visible !important;
}}
#slurm-beat-mask::after {{
    content: "";
    position: absolute;
    /* bottom:100% places the pseudo-element's bottom at the panel's top
       edge.  Max rises from the GIF's bottom frame, which is anchored here,
       so he appears to emerge from behind the panel on hover. */
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    /* 240×167 px preserves the 800:556 source aspect ratio exactly. */
    width: 240px;
    height: 167px;
    background-image: url("data:image/gif;base64,{_MAX_FIRE_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: bottom center;
    opacity: 0;
    pointer-events: none;
    /* Simple fade in/out — the GIF supplies its own motion. */
    transition: opacity 0.18s ease;
    z-index: 9999;
    filter: drop-shadow(0 8px 24px rgba(0,0,0,0.75));
}}
#slurm-beat-mask:hover::after {{
    opacity: 1;
}}
"""


CUSTOM_CSS += """
/* ═══════════════════════════════════════════════════════════════════════
   COMPACT FORM CONTROLS — global (all skins)
   • gr.Radio renders as a fieldset with one <label> per option. We restyle
     as a tight chip row, hide the native dot (cyan-bordered fill is the
     selection cue), and let labels wrap naturally.
   • gr.Dropdown's actual visible white box is hard to target generically;
     we add elem_classes=["slurm-dropdown"] to each Dropdown and force every
     descendant dark via the universal selector — bypasses class-name guessing.
   • gr.Audio's empty-state drop zone is ~400px tall by default; we add
     elem_classes=["slurm-audio"] and aggressively shrink min-height/padding/
     icon. Once audio loads, the waveform sets its own height — only the
     empty placeholder is affected.
   ═══════════════════════════════════════════════════════════════════════ */

/* ── Radio: chip-row layout ──────────────────────────────────────────── */
.gradio-container fieldset {
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
    background: transparent !important;
}
.gradio-container fieldset > .wrap,
.gradio-container [role="radiogroup"] {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 4px !important;
}
.gradio-container fieldset label,
.gradio-container [role="radiogroup"] label {
    background: #0e0c0c !important;
    border: 1px solid #2a2323 !important;
    border-radius: 4px !important;
    padding: 3px 9px !important;
    min-height: unset !important;
    min-width: unset !important;
    height: auto !important;
    font-size: 0.78rem !important;
    line-height: 1.5 !important;
    color: #8a8080 !important;
    cursor: pointer;
    transition: color 0.12s, border-color 0.12s, background 0.12s;
    box-shadow: none !important;
    display: inline-flex !important;
    align-items: center !important;
    gap: 0 !important;
}
.gradio-container fieldset label:hover,
.gradio-container [role="radiogroup"] label:hover {
    color: #cdc6c6 !important;
    border-color: #00b9e1 !important;
}
.gradio-container fieldset label:has(input:checked),
.gradio-container [role="radiogroup"] label:has(input:checked) {
    background: #0d2730 !important;
    border-color: #00b9e1 !important;
    color: #00b9e1 !important;
}
.gradio-container fieldset label input[type="radio"],
.gradio-container [role="radiogroup"] label input[type="radio"] {
    display: none !important;
}
.gradio-container .slurm-max-option {
    padding-left: 11px !important;
    padding-right: 11px !important;
}

/* Kill the scrollbar Gradio puts on the radio wrapper. With chip-row
   layout the chips wrap naturally so vertical scroll is unnecessary. */
.gradio-container fieldset,
.gradio-container [role="radiogroup"],
.gradio-container .gradio-radio,
.gradio-container [data-testid="radio-component"],
.gradio-container [data-testid*="radio"] {
    overflow: visible !important;
    max-height: none !important;
}
/* Also unconstrain the block wrapper that contains the radio */
.gradio-container .block:has(> fieldset),
.gradio-container .block:has([role="radiogroup"]) {
    overflow: visible !important;
    max-height: none !important;
}

/* ── Dropdown: dark theme + compact (via elem_classes=["slurm-dropdown"]) ─ */
.gradio-container .slurm-dropdown,
.gradio-container .slurm-dropdown * {
    background-color: #0e0c0c !important;
    color: #cdc6c6 !important;
    border-color: #2a2323 !important;
    box-shadow: none !important;
}
.gradio-container .slurm-dropdown {
    background-color: transparent !important;
}
.gradio-container .slurm-dropdown > .wrap,
.gradio-container .slurm-dropdown .wrap-inner,
.gradio-container .slurm-dropdown .container {
    background-color: #0e0c0c !important;
    border: 1px solid #2a2323 !important;
    border-radius: 5px !important;
    padding: 3px 8px !important;
    min-height: 30px !important;
}
.gradio-container .slurm-dropdown input,
.gradio-container .slurm-dropdown [role="combobox"],
.gradio-container .slurm-dropdown [role="textbox"] {
    background: transparent !important;
    color: #cdc6c6 !important;
    font-size: 0.82rem !important;
    padding: 0 !important;
    min-height: unset !important;
    height: auto !important;
}
.gradio-container .slurm-dropdown svg {
    background: transparent !important;
    color: #6a6060 !important;
    fill: currentColor !important;
}
/* Popup options list (rendered in document body, not inside the wrapper) */
.gradio-container .options,
.gradio-container ul[role="listbox"],
body > .options,
body > ul[role="listbox"] {
    background: #161314 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 5px !important;
    box-shadow: 0 6px 18px rgba(0,0,0,0.5) !important;
    color: #cdc6c6 !important;
}
.gradio-container .options .item,
.gradio-container .options li,
.gradio-container ul[role="listbox"] li,
body > .options .item,
body > ul[role="listbox"] li {
    color: #cdc6c6 !important;
    font-size: 0.82rem !important;
    padding: 4px 10px !important;
    background: transparent !important;
}
.gradio-container .options .item:hover,
.gradio-container .options li:hover,
.gradio-container ul[role="listbox"] li:hover,
body > .options .item:hover,
body > ul[role="listbox"] li:hover {
    background: #1e1a1b !important;
    color: #00b9e1 !important;
}
.gradio-container .options .selected,
.gradio-container ul[role="listbox"] [aria-selected="true"],
body > .options .selected,
body > ul[role="listbox"] [aria-selected="true"] {
    background: #0d2730 !important;
    color: #00b9e1 !important;
}

/* ── Audio drop zone: kill min-height, let Gradio size naturally ─────── */
/* Earlier attempts used max-height to cap empty-state size, but that
   clipped the transport controls (play/time/skip) on loaded audio. Now
   we just remove min-height so the empty state can shrink, keep tight
   padding, and let Gradio's natural sizing handle the loaded state.
   Output components keep transport controls when audio is loaded. */
.gradio-container .slurm-audio {
    min-height: 0 !important;
}
.gradio-container .slurm-audio > * {
    min-height: 0 !important;
}
.gradio-container .slurm-audio svg {
    width: 22px !important;
    height: 22px !important;
}
.gradio-container .slurm-audio .or,
.gradio-container .slurm-audio [class*="or"] {
    margin: 0 !important;
    font-size: 0.72rem !important;
    line-height: 1.15 !important;
}

/* ═══════════════════════════════════════════════════════════════════════
   DEFAULT SKIN ONLY: tighten vertical rhythm
   Acid + Hardware skins use more generous spacing on purpose.
   ═══════════════════════════════════════════════════════════════════════ */
body[data-skin="default"] .gradio-container .info,
body[data-skin="default"] .gradio-container [class*="info"] {
    font-size: 0.65rem !important;
    margin-top: 1px !important;
    margin-bottom: 3px !important;
    line-height: 1.25 !important;
}
body[data-skin="default"] .gradio-container .gap.column,
body[data-skin="default"] .gradio-container .form > .form,
body[data-skin="default"] .gradio-container [class*="column"] > .gap {
    gap: 4px !important;
}

/* ── Beat mask chip strip ─────────────────────────────────────────────────
   #slurm-beat-mask is a plain <div> injected by gr.HTML() immediately below
   the resolution Radio component.  _slurmBuildBeatMask() in INIT_JS writes
   the chip buttons into it dynamically whenever the resolution changes.

   Layout:
     .slurm-beat-mask-label  — small descriptor line above the chip row
     .slurm-beat-mask-row    — flex row of .slurm-bar-chip buttons
     .slurm-bar-chip-on     — beat is ACTIVE (cyan, filled)
     .slurm-bar-chip-off    — beat is DROPPED (dark, dashed border)
   ────────────────────────────────────────────────────────────────────── */
#slurm-beat-mask {
    margin-top: 6px;
    margin-bottom: 2px;
    padding: 6px 8px;
    background: #111010;
    border: 1px solid #1e1a1b;
    border-radius: 6px;
}

.slurm-beat-mask-label {
    font-size: 0.62rem;
    color: #5a5252;
    letter-spacing: 0.03em;
    margin-bottom: 5px;
    text-transform: lowercase;
}

.slurm-beat-mask-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}

/* Base chip button — shared properties */
.slurm-bar-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 28px;
    height: 28px;
    padding: 0 4px;
    font-size: 0.85rem;        /* circled digit glyphs are a bit larger */
    line-height: 1;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.12s, color 0.12s, border-color 0.12s,
                box-shadow 0.12s;
    box-shadow: none;
    outline: none;
    user-select: none;
    /* At 16 chips (1/16) on a narrow column, chips wrap to 2 rows —
       flex-wrap on the parent row handles this gracefully. */
}

/* ON state: beat is active — filled cyan */
.slurm-bar-chip-on {
    background: #0d2730;
    color: #00b9e1;
    border: 1px solid #00b9e1;
}
.slurm-bar-chip-on:hover {
    background: #103540;
    border-color: #33c9e8;
    color: #33c9e8;
    box-shadow: 0 0 6px rgba(0,185,225,0.25);
}

/* OFF state: beat is dropped — dark, dashed border to signal "skip" */
.slurm-bar-chip-off {
    background: #100d0d;
    color: #3a3232;
    border: 1px dashed #2a2323;
}
.slurm-bar-chip-off:hover {
    background: #161314;
    color: #6a5f5f;
    border-color: #4a3f3f;
}

/* Acid skin: glow on selected chips */
body[data-skin="acid"] .slurm-bar-chip-on {
    box-shadow: 0 0 8px rgba(0,255,200,0.3);
    border-color: #00ffc8;
    color: #00ffc8;
    background: #051a12;
}
body[data-skin="acid"] .slurm-bar-chip-off {
    border-color: #1a1a0a;
    color: #2a2a1a;
}

/* Hardware skin: LED-style chips */
body[data-skin="hardware"] .slurm-bar-chip-on {
    background: #001800;
    border-color: #00c040;
    color: #00c040;
    box-shadow: 0 0 5px rgba(0,192,64,0.4);
    font-family: monospace;
}
body[data-skin="hardware"] .slurm-bar-chip-off {
    background: #060606;
    border-color: #1a2a1a;
    color: #1a2a1a;
}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# Icon assets — Subvoyant / Siena cat logo
# ───────────────────────────────────────────────────────────────────────────────
# _ICON_B64  : base64-encoded PNG of the Subvoyant icon.  Used in two places:
#                1. The browser favicon — injected by the JS favicon-retry loop
#                   inside INIT_JS § 6 (the only reliable place to set a Gradio
#                   favicon; both the head= kwarg and favicon_path= get
#                   overridden at runtime — ADR-0010).
#                2. The <img> inside _ICON_TAG (the clickable header logo).
#
# _ICON_TAG  : pre-assembled <a><img></a> HTML string.  Inserted into the page
#              header via gr.HTML(_ICON_TAG) inside build_ui().  Clicking it
#              opens subvoyant.com in a new tab.
# ═══════════════════════════════════════════════════════════════════════════════
_ICON_B64 = "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"
_ICON_TAG  = (
    '<a href="https://www.subvoyant.com" target="_blank" '
    'rel="noopener noreferrer" class="slurm-header-link" '
    'aria-label="Visit subvoyant.com">'
    '<img src="data:image/png;base64,' + _ICON_B64 +
    '" class="slurm-icon" alt="Subvoyant" />'
    '</a>'
)


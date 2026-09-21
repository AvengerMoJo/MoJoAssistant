# GUI Agent Capability — Framework Outline

Date: 2026-09-18
Status: Outline — open questions pending Rebecca's landscape study (see §7)

## 1. Motivation

MoJoAssistant manages third-party coding agents today as **headless, text-in/text-out**
servers (opencode REST, or the legacy MCP bridge). That covers "project development"
work, but a general third-party agent framework must also handle work that requires a
visible UI: Amuse on Windows, TinYi-style business automation, browser/web workflows,
and mobile/desktop apps.

UI-handling should be a **general agent capability**, not something bolted onto one
project. This doc frames that capability as a first-class, cross-platform abstraction.

Scope note: **how the vision model supplies perception is deliberately out of scope
here.** This outline defines the framework contract and the axis along which UI-capable
hosts plug in; the perception plumbing behind it is covered separately.

## 2. The Gap: One Axis Modeled Today, Two Needed

Today MoJoAssistant models exactly one axis per host/backend:

- **Execution backend** — *where code runs*: `host`, `cube` (KVM microVM), `docker`,
  `ssh`, plus bridge hosts (`opencode_serve` / `legacy_mcp`). Every one wraps a headless
  opencode server that acts on a repo + terminal. **None has screen/UI access.**

The framework has no vocabulary for a second, orthogonal axis:

- **Interface modality** — *how the agent perceives and acts on a UI*.

Closing that gap means treating UI capability as a property a host declares, so
deployment stays declarative and dispatch works by capability, not by hardcoded
"coding agent vs GUI agent" roles.

## 3. Capability Envelope (Proposed)

Each host/backend registry entry gains an `interface` envelope in addition to
`execution`. Two orthogonal dimensions on every deployment:

```
execution          interface
(where it runs)    (how it sees + acts)
──────────────     ────────────────────
host               headless   (tools + terminal — today's agents only)
cube               gui        (desktop apps: Windows/macOS/Linux)
docker             webui      (browser DOM + input)
ssh                android_ui (adb screencap + tap/swipe)
legacy_mcp         macos_ui   (screen + accessibility)
                   ios_ui     (screen + native automation)
```

Proposed registry shape (extends the existing host entry in
`~/.memory/config/agent_bridge.json`):

```jsonc
"some-ui-host": {
  "backend": "windows_gui",              // execution: how code runs
  "interface": ["gui", "webui"],         // sensing + input modes available
  "sensing": ["screen", "uia"],          // perception channels
  "input_modes": ["mouse", "keyboard"],
  "os": "windows"
}
```

Multiple `interface` entries per host are expected (one machine can serve desktop GUI
**and** a browser). Dispatch then asks: *does this host declare the modality the task
needs?* Same mental model as the existing [Capability Abstraction Contract](./CAPABILITY_ABSTRACTION_CONTRACT.md),
extended from task-side intent classes to host-side modality envelopes.

## 4. Modality Adapter Contract (one interface, many backends)

The framework exposes **one adapter contract per modality**; deployment-specific
plumbing (perception source, input mechanism, IPC) lives behind it. This is the "don't
bikeshed the vision pipeline" boundary — the contract is what matters.

| modality    | perception channels        | input                                | existing plumbing in our stack         |
|-------------|----------------------------|--------------------------------------|----------------------------------------|
| `webui`     | browser DOM, screen grab   | mouse, keyboard, scroll              | Playwright (Bao), browser automation   |
| `gui`       | screen, accessibility tree | mouse, keyboard                      | VNC / RDP (used in TinYi), desktop IPC |
| `android_ui`| adb screencap, view dump   | tap, swipe, text, keyevents          | adb (done on Mac desktop)              |
| `macos_ui`  | screen, accessibility      | mouse, keyboard, gestures            | macOS frameworks                       |
| `ios_ui`    | screen (via tooling)       | touch, gestures (no device on hand)  | — (deferred, no test device)           |

## 5. Execution Models Overlaid

Reserving the option to run the UI *inside* or *outside* the execution sandbox:

- **Local**: UI host is the machine (e.g. Amuse desktop on a Windows box).
- **Remote/headless**: UI rendered in a remote session (VNC/RDP) driven through the
  agent — repeated pattern in TinYi projects already.
- **Virtualized**: screen inside a microVM (cube) or container for isolation.

The envelope records which model applies; dispatch and the adapter use it.

## 6. What Changes

| capability                          | today | target                          |
|-------------------------------------|-------|---------------------------------|
| headless coding agents              | done  | unchanged                       |
| registry declares interface/modality| no    | add `interface/sensing/input/os`|
| one adapter contract per modality   | no    | define (gui, webui, android_ui…)|
| virtualized/remote UI (VNC/RDP)     | ad hoc in projects | first-class       |
| dispatch by capability              | no    | modality-aware dispatch         |
| perception/vision plumbing          | n/a   | deferred (§1)                   |

## 7. Landscape Study (Assigned) — Rebecca

Open questions the outline deliberately does NOT answer yet:

1. Which open-source GUI / desktop / vision-agent frameworks exist and are maintained?
2. How ready is each for MoJoAssistant integration (API/IPC, license, activeness)?
3. Which cover `gui` vs `webui` vs mobile; any one framework covering several?
4. What is the state of the category generally (not just "Amuse or TinYi") — is this a
   solved problem or an emerging one?

Assigned to Rebecca (researcher). The doc's conclusions update after her study; nothing
in §3–§6 above is treated as settled until the integration-readiness matrix exists there.

## 8. Proven Internal Experience (Calibration for the Study)

Owned knowledge to weight the study against, not rediscovers:

- `webui`: automated browser flows in TinYi projects.
- `android_ui`: adb-driven Android automation done on a Mac local desktop.
- `gui remote`: VNC / RDP-driven UI automation done in TinYi projects.
- `macos_ui` / `ios_ui`: least-owned; iOS additionally has no test device.
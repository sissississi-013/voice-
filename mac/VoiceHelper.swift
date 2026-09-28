// Voice: type "@v" (or "@v <hint>") in any app — Messages, Chrome, Slack, WeChat, Notes… —
// and get 3 drafts in your voice. No browser plugin needed.
//
// Build: swiftc -O -o VoiceHelper VoiceHelper.swift -framework Cocoa
// Run:   ./VoiceHelper   (needs Accessibility permission; server.py must be running)
//
// Apple APIs only: Accessibility reads the focused field + the conversation/page around it and
// writes the chosen draft back; AppKit draws the bubble. Drafts come from server.py in two phases:
// /draft returns fast base drafts (~2s), then /voice restyles each one with the River LoRA.

import Cocoa
import ApplicationServices

let server = "http://127.0.0.1:8765"
let trigger = try! NSRegularExpression(pattern: #"(^|\s)@v(?:\s+(.*))?$"#, options: [.dotMatchesLineSeparators])
let debounce = 0.7

// MARK: - Accessibility helpers

func attr(_ el: AXUIElement, _ name: String) -> AnyObject? {
    var value: AnyObject?
    return AXUIElementCopyAttributeValue(el, name as CFString, &value) == .success ? value : nil
}

func str(_ el: AXUIElement, _ name: String) -> String? { attr(el, name) as? String }

func frame(of el: AXUIElement) -> CGRect? {
    guard let p = attr(el, kAXPositionAttribute), let s = attr(el, kAXSizeAttribute) else { return nil }
    var point = CGPoint.zero, size = CGSize.zero
    AXValueGetValue(p as! AXValue, .cgPoint, &point)
    AXValueGetValue(s as! AXValue, .cgSize, &size)
    return CGRect(origin: point, size: size)
}

/// Chrome and Electron apps (Slack, Discord, …) only expose web content once asked.
var enabledPIDs = Set<pid_t>()
func enableWebAccessibility(_ app: AXUIElement, pid: pid_t) {
    guard !enabledPIDs.contains(pid) else { return }
    enabledPIDs.insert(pid)
    AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
}

/// The part of the window worth reading: the web page if we're in one, else the whole window.
func contextRoot(for field: AXUIElement, window: AXUIElement) -> AXUIElement {
    var node: AXUIElement? = field
    for _ in 0..<60 {
        guard let current = node else { break }
        if str(current, kAXRoleAttribute) == "AXWebArea" { return current }
        node = attr(current, kAXParentAttribute).map { $0 as! AXUIElement }
    }
    return window
}

/// Visible text around the field, top to bottom (newest messages end up last).
func readContext(root: AXUIElement, skipping field: AXUIElement) -> String {
    var lines: [String] = []
    var seen = Set<String>()
    var budget = 2500
    func walk(_ el: AXUIElement, depth: Int) {
        guard depth < 60, budget > 0 else { return }
        budget -= 1
        if CFEqual(el, field) { return }
        let role = str(el, kAXRoleAttribute) ?? ""
        if role == "AXButton" || role == "AXMenuBar" || role == "AXToolbar" { return }
        if role == "AXStaticText" || role == "AXTextArea" || role == "AXCell" || role == "AXGroup" || role == "AXHeading" {
            for key in [kAXValueAttribute, kAXDescriptionAttribute] {
                if let t = str(el, key)?.trimmingCharacters(in: .whitespacesAndNewlines),
                   t.count > 1, !seen.contains(t) {
                    seen.insert(t)
                    lines.append(t)
                    break
                }
            }
        }
        for child in (attr(el, kAXChildrenAttribute) as? [AXUIElement]) ?? [] { walk(child, depth: depth + 1) }
    }
    walk(root, depth: 0)
    return String(lines.joined(separator: "\n").suffix(6000))
}

func post(_ path: String, _ body: [String: Any], done: @escaping ([String: Any]?, String?) -> Void) {
    var req = URLRequest(url: URL(string: server + path)!)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.timeoutInterval = 60
    req.httpBody = try? JSONSerialization.data(withJSONObject: body)
    URLSession.shared.dataTask(with: req) { data, _, error in
        let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        DispatchQueue.main.async { done(json, error?.localizedDescription ?? json?["error"] as? String) }
    }.resume()
}

// MARK: - Bubble UI

final class Bubble: NSPanel {
    var onPick: ((String) -> Void)?
    private let stack = NSStackView()
    private var anchor = CGRect.zero

    init() {
        super.init(contentRect: NSRect(x: 0, y: 0, width: 380, height: 60),
                   styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
        level = .popUpMenu
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let box = NSVisualEffectView()
        box.material = .popover
        box.state = .active
        box.wantsLayer = true
        box.layer?.cornerRadius = 14
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 4
        stack.edgeInsets = NSEdgeInsets(top: 8, left: 8, bottom: 8, right: 8)
        stack.translatesAutoresizingMaskIntoConstraints = false
        box.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: box.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: box.trailingAnchor),
            stack.topAnchor.constraint(equalTo: box.topAnchor),
            stack.bottomAnchor.constraint(equalTo: box.bottomAnchor),
            stack.widthAnchor.constraint(equalToConstant: 380),
        ])
        contentView = box
    }

    func show(status: String, options: [(text: String, voiced: Bool)] = [], near rect: CGRect? = nil) {
        if let rect { anchor = rect }
        stack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let label = NSTextField(labelWithString: status)
        label.font = .systemFont(ofSize: 11)
        label.textColor = .secondaryLabelColor
        stack.addArrangedSubview(label)
        for (i, option) in options.enumerated() {
            let button = NSButton(title: "\(i + 1). \(option.text)\(option.voiced ? "" : "  …")",
                                  target: self, action: #selector(picked(_:)))
            button.bezelStyle = .inline
            button.alignment = .left
            button.lineBreakMode = .byWordWrapping
            button.contentTintColor = option.voiced ? .labelColor : .secondaryLabelColor
            button.identifier = NSUserInterfaceItemIdentifier(option.text)
            button.widthAnchor.constraint(equalToConstant: 364).isActive = true
            stack.addArrangedSubview(button)
        }
        layoutIfNeeded()
        let height = stack.fittingSize.height
        // AX uses top-left origin on the primary screen; AppKit uses bottom-left.
        let screenHeight = NSScreen.screens.first?.frame.height ?? 0
        var y = screenHeight - anchor.minY + 8                  // above the field
        if y + height > screenHeight { y = screenHeight - anchor.maxY - height - 8 }  // else below
        setFrame(NSRect(x: anchor.minX, y: y, width: 380, height: height), display: true)
        orderFrontRegardless()
    }

    @objc private func picked(_ sender: NSButton) {
        if let text = sender.identifier?.rawValue { onPick?(text) }
    }
}

// MARK: - Watcher

final class Helper {
    let bubble = Bubble()
    let axQueue = DispatchQueue(label: "voice.ax")
    var lastValue = ""
    var pending: DispatchWorkItem?
    var requestID = 0
    var activeField: AXUIElement?
    var options: [(text: String, voiced: Bool)] = []

    init() {
        bubble.onPick = { [weak self] text in self?.insert(text) }
        Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in self?.tick() }
    }

    func hide() { if bubble.isVisible { bubble.orderOut(nil) } }

    func tick() {
        guard let app = NSWorkspace.shared.frontmostApplication,
              app.processIdentifier != ProcessInfo.processInfo.processIdentifier else { return }
        let axApp = AXUIElementCreateApplication(app.processIdentifier)
        enableWebAccessibility(axApp, pid: app.processIdentifier)
        guard let focused = attr(axApp, kAXFocusedUIElementAttribute) else { return }
        let field = focused as! AXUIElement
        let subrole = str(field, kAXSubroleAttribute) ?? ""
        if subrole == "AXSecureTextField" || subrole == "AXSearchField" { return }
        let value = str(field, kAXValueAttribute) ?? ""
        guard value != lastValue else { return }
        lastValue = value
        pending?.cancel()
        let ns = value as NSString
        guard let m = trigger.firstMatch(in: value, range: NSRange(location: 0, length: ns.length)) else {
            hide()
            return
        }
        let hint = m.range(at: 2).location != NSNotFound ? ns.substring(with: m.range(at: 2)) : ""
        let before = ns.substring(to: m.range.location).trimmingCharacters(in: .whitespacesAndNewlines)
        let rect = frame(of: field) ?? .zero
        let appName = app.localizedName ?? "app"
        activeField = field
        requestID += 1
        let id = requestID
        bubble.show(status: "✨ @v \(hint.isEmpty ? "" : "— \(hint) ")· \(appName)", near: rect)
        let work = DispatchWorkItem { [weak self] in
            // Read context off the main thread; AX calls are IPC and can take a moment.
            self?.axQueue.async {
                let window = attr(axApp, kAXFocusedWindowAttribute).map { $0 as! AXUIElement }
                let title = window.flatMap { str($0, kAXTitleAttribute) } ?? ""
                let context = window.map { readContext(root: contextRoot(for: field, window: $0), skipping: field) } ?? ""
                DispatchQueue.main.async {
                    guard let self, id == self.requestID else { return }
                    self.draft(id: id, text: before, hint: hint, site: "\(appName) — \(title)", context: context)
                }
            }
        }
        pending = work
        DispatchQueue.main.asyncAfter(deadline: .now() + debounce, execute: work)
    }

    func draft(id: Int, text: String, hint: String, site: String, context: String) {
        bubble.show(status: "✨ drafting…")
        post("/draft", ["text": text, "hint": hint, "site": site, "field": "message box",
                        "context": "CONVERSATION / PAGE (oldest to newest; reply to the NEWEST message):\n\(context)"]) { [weak self] json, problem in
            guard let self, id == self.requestID else { return }
            let drafts = json?["drafts"] as? [String] ?? []
            if drafts.isEmpty {
                self.bubble.show(status: "hiccup: \(problem ?? "no drafts") (is server.py running?)")
                return
            }
            // Phase 1: show base drafts right away. Phase 2: swap each for its voiced version.
            self.options = drafts.map { ($0, false) }
            self.render()
            for (i, d) in drafts.enumerated() {
                post("/voice", ["text": d, "temperature": [0.3, 0.6, 0.9][i % 3]]) { [weak self] json, _ in
                    guard let self, id == self.requestID, i < self.options.count else { return }
                    let voiced = (json?["text"] as? String) ?? d
                    self.options[i] = (voiced, true)
                    self.render()
                }
            }
        }
    }

    func render() {
        let done = options.allSatisfy(\.voiced)
        bubble.show(status: done ? "✨ in your voice · click to insert (you still hit Enter)"
                                 : "✨ drafts ready · turning them into your voice…", options: options)
    }

    func insert(_ text: String) {
        requestID += 1
        hide()
        guard let field = activeField else { return }
        if AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, text as CFString) == .success,
           str(field, kAXValueAttribute) == text {
            lastValue = text
            return
        }
        // Fallback for web/Electron editors: select all in the field, paste.
        AXUIElementSetAttributeValue(field, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let board = NSPasteboard.general
        let saved = board.string(forType: .string)
        board.clearContents()
        board.setString(text, forType: .string)
        for key: CGKeyCode in [0, 9] { // A, V
            for down in [true, false] {
                let e = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: down)
                e?.flags = .maskCommand
                e?.post(tap: .cghidEventTap)
            }
        }
        lastValue = text
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            if let saved { board.clearContents(); board.setString(saved, forType: .string) }
        }
    }
}

// MARK: - Main

setvbuf(stdout, nil, _IOLBF, 0)
let prompt = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
if !AXIsProcessTrustedWithOptions(prompt) {
    print("Grant Accessibility: System Settings → Privacy & Security → Accessibility → enable your terminal, then rerun.")
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let helper = Helper()
print("Voice running. In any app, type @v (or @v <hint>).")
app.run()

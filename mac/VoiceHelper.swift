// Voice for iMessage: type "@v" (optionally "@v <hint>") in Messages and get 3 drafts in your voice.
//
// Build: swiftc -O -o VoiceHelper VoiceHelper.swift -framework Cocoa
// Run:   ./VoiceHelper   (needs Accessibility permission; server.py must be running)
//
// Uses only Apple APIs: Accessibility (read the focused field + visible conversation,
// write the chosen draft back), AppKit (floating bubble). Drafts come from server.py.

import Cocoa
import ApplicationServices

let messagesBundle = "com.apple.MobileSMS"
let serverURL = URL(string: "http://127.0.0.1:8765/suggest")!
let trigger = try! NSRegularExpression(pattern: #"(^|\s)@v(?:\s+(.*))?$"#, options: [.dotMatchesLineSeparators])

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

/// Collect visible transcript text from the Messages window, top to bottom.
func conversationText(in window: AXUIElement, skipping field: AXUIElement) -> String {
    var lines: [String] = []
    var seen = Set<String>()
    var budget = 4000
    func walk(_ el: AXUIElement, depth: Int) {
        guard depth < 40, budget > 0 else { return }
        budget -= 1
        if CFEqual(el, field) { return }
        let role = str(el, kAXRoleAttribute) ?? ""
        for key in [kAXValueAttribute, kAXDescriptionAttribute, kAXTitleAttribute] {
            if let t = str(el, key)?.trimmingCharacters(in: .whitespacesAndNewlines),
               t.count > 1, role != "AXButton", !seen.contains(t) {
                seen.insert(t)
                lines.append(t)
                break
            }
        }
        for child in (attr(el, kAXChildrenAttribute) as? [AXUIElement]) ?? [] { walk(child, depth: depth + 1) }
    }
    walk(window, depth: 0)
    let text = lines.joined(separator: "\n")
    return String(text.suffix(9000))
}

// MARK: - Bubble UI

final class Bubble: NSPanel {
    var onPick: ((String) -> Void)?
    private let stack = NSStackView()

    init() {
        super.init(contentRect: NSRect(x: 0, y: 0, width: 360, height: 60),
                   styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
        level = .floating
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
            stack.widthAnchor.constraint(equalToConstant: 360),
        ])
        contentView = box
    }

    func show(status: String, options: [String] = [], near rect: CGRect) {
        stack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let label = NSTextField(labelWithString: status)
        label.font = .systemFont(ofSize: 11)
        label.textColor = .secondaryLabelColor
        stack.addArrangedSubview(label)
        for (i, option) in options.enumerated() {
            let button = NSButton(title: "\(i + 1). \(option)", target: self, action: #selector(picked(_:)))
            button.bezelStyle = .inline
            button.alignment = .left
            button.lineBreakMode = .byWordWrapping
            button.identifier = NSUserInterfaceItemIdentifier(option)
            button.widthAnchor.constraint(equalToConstant: 344).isActive = true
            stack.addArrangedSubview(button)
        }
        layoutIfNeeded()
        let size = stack.fittingSize
        // AX coordinates are top-left origin; AppKit is bottom-left.
        let screenHeight = NSScreen.screens.first?.frame.height ?? 0
        let top = screenHeight - rect.minY + 8
        setFrame(NSRect(x: rect.minX, y: top, width: 360, height: size.height), display: true)
        orderFrontRegardless()
    }

    @objc private func picked(_ sender: NSButton) {
        if let text = sender.identifier?.rawValue { onPick?(text) }
    }
}

// MARK: - Watcher

final class Helper {
    let bubble = Bubble()
    var lastValue = ""
    var pending: DispatchWorkItem?
    var requestID = 0
    var activeField: AXUIElement?

    init() {
        bubble.onPick = { [weak self] text in self?.insert(text) }
        Timer.scheduledTimer(withTimeInterval: 0.3, repeats: true) { [weak self] _ in self?.tick() }
    }

    func messagesApp() -> NSRunningApplication? {
        let app = NSWorkspace.shared.frontmostApplication
        return app?.bundleIdentifier == messagesBundle ? app : nil
    }

    func tick() {
        guard let app = messagesApp() else { if bubble.isVisible { bubble.orderOut(nil) }; return }
        let axApp = AXUIElementCreateApplication(app.processIdentifier)
        guard let focused = attr(axApp, kAXFocusedUIElementAttribute) else { return }
        let field = focused as! AXUIElement
        let value = str(field, kAXValueAttribute) ?? ""
        guard value != lastValue else { return }
        lastValue = value
        pending?.cancel()
        let ns = value as NSString
        guard let m = trigger.firstMatch(in: value, range: NSRange(location: 0, length: ns.length)) else {
            if bubble.isVisible { bubble.orderOut(nil) }
            return
        }
        let hint = m.range(at: 2).location != NSNotFound ? ns.substring(with: m.range(at: 2)) : ""
        let before = ns.substring(to: m.range.location).trimmingCharacters(in: .whitespacesAndNewlines)
        let rect = frame(of: field) ?? .zero
        activeField = field
        bubble.show(status: "✨ @v \(hint.isEmpty ? "" : "— \(hint) ")(keep typing a hint, or wait)", near: rect)
        let work = DispatchWorkItem { [weak self] in
            guard let window = attr(axApp, kAXFocusedWindowAttribute) else { return }
            let context = conversationText(in: window as! AXUIElement, skipping: field)
            self?.request(text: before, hint: hint, context: context, near: rect)
        }
        pending = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.1, execute: work)
    }

    func request(text: String, hint: String, context: String, near rect: CGRect) {
        requestID += 1
        let id = requestID
        bubble.show(status: "✨ drafting in your voice…", near: rect)
        var req = URLRequest(url: serverURL)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 60
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "text": text, "hint": hint, "site": "iMessage (Messages app)", "field": "iMessage reply",
            "context": "CONVERSATION (oldest to newest; reply to the NEWEST message):\n\(context)",
        ])
        URLSession.shared.dataTask(with: req) { [weak self] data, _, error in
            let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let options = json?["suggestions"] as? [String] ?? []
            let problem = error?.localizedDescription ?? json?["error"] as? String
            DispatchQueue.main.async {
                guard let self, id == self.requestID else { return }
                if options.isEmpty {
                    self.bubble.show(status: "hiccup: \(problem ?? "no drafts") (is server.py running?)", near: rect)
                } else {
                    self.bubble.show(status: "✨ in your voice: click to insert (you still hit Enter)", options: options, near: rect)
                }
            }
        }.resume()
    }

    func insert(_ text: String) {
        bubble.orderOut(nil)
        guard let field = activeField else { return }
        if AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, text as CFString) == .success,
           str(field, kAXValueAttribute) == text {
            lastValue = text
            return
        }
        // Fallback: select all + paste.
        let board = NSPasteboard.general
        let saved = board.string(forType: .string)
        board.clearContents()
        board.setString(text, forType: .string)
        for key: CGKeyCode in [0, 9] { // 0 = A, 9 = V
            for down in [true, false] {
                let e = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: down)
                e?.flags = .maskCommand
                e?.post(tap: .cghidEventTap)
            }
        }
        lastValue = text
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            if let saved { board.clearContents(); board.setString(saved, forType: .string) }
        }
    }
}

// MARK: - Main

let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
if !AXIsProcessTrustedWithOptions(options) {
    print("Grant Accessibility: System Settings → Privacy & Security → Accessibility → enable your terminal, then rerun.")
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let helper = Helper()
print("Voice helper running. In Messages, type @v (or @v <hint>).")
app.run()

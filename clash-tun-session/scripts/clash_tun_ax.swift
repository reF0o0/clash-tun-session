import AppKit
import ApplicationServices

struct DriverFailure: Error { let message: String }
func attr(_ element: AXUIElement, _ key: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, key as CFString, &value) == .success ? value : nil
}
func text(_ element: AXUIElement) -> String {
    ["AXTitle", "AXDescription", "AXValue"].compactMap { attr(element, $0) as? String }
        .joined(separator: " ").filter { !$0.isWhitespace }
}
func nodes(_ root: AXUIElement) -> [AXUIElement] {
    var queue: [(AXUIElement, Int)] = [(root, 0)]
    var result: [AXUIElement] = []
    var seen = Set<CFHashCode>()
    var cursor = 0
    while cursor < queue.count && result.count < 3000 {
        let (element, depth) = queue[cursor]; cursor += 1
        guard seen.insert(CFHash(element)).inserted else { continue }
        result.append(element)
        if depth < 18, let children = attr(element, "AXChildren") as? [AXUIElement] {
            queue.append(contentsOf: children.map { ($0, depth + 1) })
        }
    }
    return result
}
func press(_ element: AXUIElement) throws {
    guard AXUIElementPerformAction(element, kAXPressAction as CFString) == .success else {
        throw DriverFailure(message: "Clash control could not be pressed; no coordinate fallback was used")
    }
}
func waitFor(_ timeout: TimeInterval, _ body: () throws -> AXUIElement?) throws -> AXUIElement {
    let deadline = Date().addingTimeInterval(timeout)
    repeat {
        if let result = try body() { return result }
        Thread.sleep(forTimeInterval: 0.1)
    } while Date() < deadline
    throw DriverFailure(message: "Clash UI did not expose an unambiguous TUN switch before the deadline")
}
func tunSwitch(_ root: AXUIElement) throws -> AXUIElement {
    let initial = nodes(root)
    if let home = initial.first(where: {
        attr($0, "AXRole") as? String == "AXButton" &&
        (attr($0, "AXTitle") as? String ?? "").filter({ !$0.isWhitespace }) == "首页"
    }) { try press(home) }
    let tab = try waitFor(4) {
        nodes(root).first { attr($0, "AXRole") as? String == "AXStaticText" && text($0) == "虚拟网卡模式" }
    }
    if !nodes(root).contains(where: { text($0).contains("TUN模式已") }) { try press(tab) }
    return try waitFor(5) {
        let all = nodes(root)
        guard all.contains(where: { text($0).contains("TUN模式已") }) else { return nil }
        let candidates = all.filter {
            attr($0, "AXRole") as? String == "AXCheckBox" &&
            (attr($0, "AXTitle") as? String ?? "").isEmpty &&
            (attr($0, "AXDescription") as? String ?? "").isEmpty
        }
        guard candidates.count == 1 else { return nil }
        return candidates[0]
    }
}
func main() throws {
    let args = Array(CommandLine.arguments.dropFirst())
    guard AXIsProcessTrusted() else {
        throw DriverFailure(message: "Accessibility permission is unavailable; no permission prompt or setting change was made")
    }
    if args == ["check"] { print("{\"accessibility\":true}"); return }
    guard args == ["get"] || args == ["set", "on"] || args == ["set", "off"] else {
        throw DriverFailure(message: "Expected check, get, or set on|off")
    }
    guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: "io.github.clash-verge-rev.clash-verge-rev").first else {
        throw DriverFailure(message: "Clash Verge is not running; start it manually")
    }
    let root = AXUIElementCreateApplication(app.processIdentifier)
    AXUIElementSetMessagingTimeout(root, 2)
    if (attr(root, "AXWindows") as? [AXUIElement] ?? []).isEmpty {
        let open = Process(); open.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        open.arguments = ["-g", "-a", "/Applications/Clash Verge.app"]
        try open.run(); open.waitUntilExit()
    }
    let control = try tunSwitch(root)
    guard let number = attr(control, "AXValue") as? NSNumber else {
        throw DriverFailure(message: "The TUN switch has no boolean accessibility value")
    }
    let before = number.boolValue
    let desired = args.count == 2 ? args[1] == "on" : before
    if desired != before { try press(control) }
    let verified = try waitFor(12) {
        guard let value = attr(control, "AXValue") as? NSNumber, value.boolValue == desired else { return nil }
        return control
    }
    let enabled = (attr(verified, "AXValue") as? NSNumber)?.boolValue == true
    print("{\"enabled\":\(enabled),\"changed\":\(desired != before)}")
}
do { try main() }
catch {
    let message = (error as? DriverFailure)?.message ?? String(describing: error)
    let data = try! JSONSerialization.data(withJSONObject: ["error": message], options: [.sortedKeys])
    FileHandle.standardError.write(data + Data([10])); exit(1)
}

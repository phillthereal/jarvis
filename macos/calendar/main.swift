// JarvisCalendar: prints today's events as "ISO-UTC<TAB>title" lines, or "ERR no-permission".
// Add mode (bridge, only after Filip approves): `add --no-prompt <title> <yyyy-MM-ddTHH:mm> <end> [notes]`
// (local time) -> creates the event in the default calendar, prints "OK <eventIdentifier>" or "ERR <reason>".
// Double-click once to get the macOS permission prompt; the bridge runs it with --no-prompt.
import EventKit
import Foundation

let store = EKEventStore()
let sem = DispatchSemaphore(value: 0)
var granted = EKEventStore.authorizationStatus(for: .event) == .fullAccess
if !granted && !CommandLine.arguments.contains("--no-prompt") {
    store.requestFullAccessToEvents { g, _ in granted = g; sem.signal() }
    _ = sem.wait(timeout: .now() + 120)
}
guard granted else { print("ERR no-permission status=\(EKEventStore.authorizationStatus(for: .event).rawValue)"); exit(1) }
let argv = CommandLine.arguments
if argv.count > 1 && argv[1] == "add" {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = .current; f.dateFormat = "yyyy-MM-dd'T'HH:mm"
    guard argv.count >= 6, argv[2] == "--no-prompt", let s = f.date(from: argv[4]), let e = f.date(from: argv[5]), e > s
    else { print("ERR bad-args"); exit(2) }
    guard let cal = store.defaultCalendarForNewEvents else { print("ERR no-default-calendar"); exit(1) }
    let ev = EKEvent(eventStore: store)
    ev.title = argv[3]; ev.startDate = s; ev.endDate = e; ev.calendar = cal
    if argv.count > 6 { ev.notes = argv[6] }
    do { try store.save(ev, span: .thisEvent, commit: true) } catch {
        print("ERR save-failed " + error.localizedDescription.replacingOccurrences(of: "\n", with: " ")); exit(1)
    }
    print("OK " + (ev.eventIdentifier ?? "")); exit(0)
}
let start = Calendar.current.startOfDay(for: Date())
let end = Calendar.current.date(byAdding: .day, value: 1, to: start)!
let iso = ISO8601DateFormatter()
for ev in store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil)) {
    print(iso.string(from: ev.startDate) + "\t" + (ev.title ?? "").replacingOccurrences(of: "\n", with: " "))
}

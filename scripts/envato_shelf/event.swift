// Address only the private renderer process. The owner's open AE project stays in its own instance.
import Foundation

func code(_ value: String) -> UInt32 {
    value.utf8.reduce(0) { ($0 << 8) + UInt32($1) }
}

guard CommandLine.arguments.count == 3, let pid = Int32(CommandLine.arguments[1]) else { exit(2) }
let target = NSAppleEventDescriptor(processIdentifier: pid)
let event = NSAppleEventDescriptor(eventClass: code("misc"), eventID: code("dosc"),
                                   targetDescriptor: target, returnID: -1, transactionID: 0)
event.setParam(NSAppleEventDescriptor(string: CommandLine.arguments[2]), forKeyword: code("----"))
do {
    let reply = try event.sendEvent(options: [.waitForReply, .neverInteract], timeout: 180)
    if reply.paramDescriptor(forKeyword: code("errn")) != nil { exit(1) }
} catch {
    exit(1)
}

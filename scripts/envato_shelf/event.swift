import Foundation
func code(_ s: String) -> UInt32 { s.utf8.reduce(0) { ($0 << 8) + UInt32($1) } }
let event = NSAppleEventDescriptor(eventClass: code("misc"), eventID: code("dosc"), targetDescriptor: NSAppleEventDescriptor(processIdentifier: Int32(CommandLine.arguments[1])!), returnID: -1, transactionID: 0)
event.setParam(NSAppleEventDescriptor(string: CommandLine.arguments[2]), forKeyword: code("----"))
let response = try event.sendEvent(options: [.waitForReply, .neverInteract], timeout: 180)
if let err = response.paramDescriptor(forKeyword: code("errn")) { print(err, response); exit(1) }
print(response.paramDescriptor(forKeyword: code("----"))?.stringValue ?? "(no reply text)")

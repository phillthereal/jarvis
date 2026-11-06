// KeystoneReader <file>: prints the file's text to stdout (local only, no permissions needed).
// PDF -> PDFKit text per page; a page with < 20 chars is rendered and OCR'd with Vision.
// Images (png/jpg/jpeg/heic/tiff) -> Vision OCR. Output capped at 200k chars. Failure: "ERR <reason>", exit 1.
import AppKit
import Foundation
import PDFKit
import Vision

let cap = 200_000
func fail(_ r: String) -> Never { print("ERR " + r); exit(1) }

func ocr(_ img: CGImage) -> String {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    req.recognitionLanguages = ["en-GB", "en-US"]
    do { try VNImageRequestHandler(cgImage: img).perform([req]) } catch { return "" }
    return (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func render(_ page: PDFPage) -> CGImage? {
    let box = page.bounds(for: .mediaBox), scale: CGFloat = 2.5
    let w = Int(box.width * scale), h = Int(box.height * scale)
    guard w > 0, h > 0, w * h < 120_000_000,
          let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
    else { return nil }
    ctx.setFillColor(.white); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

let args = CommandLine.arguments
guard args.count == 2 else { fail("usage: KeystoneReader <file>") }
let url = URL(fileURLWithPath: args[1])
guard FileManager.default.isReadableFile(atPath: url.path) else { fail("not-readable") }
var out = ""
switch url.pathExtension.lowercased() {
case "pdf":
    guard let doc = PDFDocument(url: url) else { fail("bad-pdf") }
    if doc.isLocked { fail("pdf-locked") }
    for i in 0..<doc.pageCount {
        guard out.count < cap, let page = doc.page(at: i) else { break }
        var t = page.string ?? ""
        if t.trimmingCharacters(in: .whitespacesAndNewlines).count < 20, let img = render(page) { t = ocr(img) }
        out += t + "\n\n"
    }
case "png", "jpg", "jpeg", "heic", "tiff", "tif":
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fail("bad-image") }
    out = ocr(img)
default:
    fail("unsupported-type")
}
print(String(out.prefix(cap)))

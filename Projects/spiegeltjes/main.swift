// Spiegeltjes — elke camera als randloos, zwevend venster. Geen titelbalk, geen schaduw, geen marges.
// Slepen = verplaatsen (snapt tegen schermranden en tegen elkaar), slepen in een hoek = schalen,
// rechtsklik = spiegelen / passend / breedte / sluiten. Menubalk-icoon: camera's aan/uit, vastzetten.
// Bouwen: ./build.sh

// bron conversatie:
// https://claude.ai/chat/57e2610b-ebe4-4e3d-99c2-f5c5ffbb4403

import AppKit
import AVFoundation
import CoreMediaIO

let D = UserDefaults.standard
let app = AppDelegate()

// Zoals QuickTime: iPhones/iPads via USB als bron tonen (scherm van het toestel)
func allowScreenCaptureDevices() {
    var a = CMIOObjectPropertyAddress(
        mSelector: CMIOObjectPropertySelector(kCMIOHardwarePropertyAllowScreenCaptureDevices),
        mScope: CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal),
        mElement: CMIOObjectPropertyElement(kCMIOObjectPropertyElementMain))
    var on: UInt32 = 1
    CMIOObjectSetPropertyData(CMIOObjectID(kCMIOObjectSystemObject), &a, 0, nil, UInt32(MemoryLayout<UInt32>.size), &on)
}

func devices() -> [AVCaptureDevice] {
    AVCaptureDevice.DiscoverySession(
        deviceTypes: [.builtInWideAngleCamera, .continuityCamera, .deskViewCamera, .external],
        mediaType: nil, position: .unspecified
    ).devices.filter { $0.hasMediaType(.video) || $0.hasMediaType(.muxed) }
}

func near(_ v: CGFloat, _ ts: [CGFloat]) -> CGFloat? {
    ts.filter { abs($0 - v) < 12 }.min { abs($0 - v) < abs($1 - v) }
}

final class Act: NSMenuItem {
    let f: () -> Void
    init(_ t: String, _ on: Bool = false, _ f: @escaping () -> Void) {
        self.f = f
        super.init(title: t, action: #selector(run), keyEquivalent: "")
        target = self; state = on ? .on : .off
    }
    required init(coder: NSCoder) { fatalError() }
    @objc func run() { f() }
}

final class CamPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override func constrainFrameRect(_ r: NSRect, to s: NSScreen?) -> NSRect { r } // mag overal, ook strak tegen de rand
}

final class CamView: NSView {
    weak var cam: Cam?
    let preview = AVCaptureVideoPreviewLayer()
    var startMouse = NSPoint.zero, startFrame = NSRect.zero
    var corner: (CGFloat, CGFloat)?

    override init(frame: NSRect) {
        super.init(frame: frame)
        layer = CALayer(); wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
        layer?.addSublayer(preview)
        fitLayer()
    }
    required init?(coder: NSCoder) { fatalError() }
    override func acceptsFirstMouse(for e: NSEvent?) -> Bool { true }
    override func setFrameSize(_ s: NSSize) { super.setFrameSize(s); fitLayer() }
    func fitLayer() {
        CATransaction.begin(); CATransaction.setDisableActions(true)
        preview.bounds = bounds; preview.position = CGPoint(x: bounds.midX, y: bounds.midY)
        CATransaction.commit()
    }

    override func mouseDown(with e: NSEvent) {
        guard let w = window else { return }
        startMouse = NSEvent.mouseLocation; startFrame = w.frame
        let p = convert(e.locationInWindow, from: nil), k: CGFloat = 24
        let nx: CGFloat = p.x < k ? -1 : (p.x > bounds.width - k ? 1 : 0)
        let ny: CGFloat = p.y < k ? -1 : (p.y > bounds.height - k ? 1 : 0)
        corner = (nx != 0 && ny != 0) ? (nx, ny) : nil
    }
    override func mouseDragged(with e: NSEvent) {
        guard let w = window else { return }
        let m = NSEvent.mouseLocation, dx = m.x - startMouse.x, dy = m.y - startMouse.y
        let sf = startFrame, (xs, ys) = app.snapTargets(excluding: w)
        var f = sf
        if let (cx, cy) = corner { // schalen vanuit een hoek, verhouding blijft
            let ar = sf.width / sf.height
            var wd = sf.width + cx * dx
            let ex = cx > 0 ? sf.minX + wd : sf.maxX - wd
            if let t = near(ex, xs) { wd = cx > 0 ? t - sf.minX : sf.maxX - t }
            else {
                let ey = cy > 0 ? sf.minY + wd / ar : sf.maxY - wd / ar
                if let t = near(ey, ys) { wd = (cy > 0 ? t - sf.minY : sf.maxY - t) * ar }
            }
            wd = max(80, wd)
            f.size = NSSize(width: wd, height: wd / ar)
            f.origin.x = cx > 0 ? sf.minX : sf.maxX - wd
            f.origin.y = cy > 0 ? sf.minY : sf.maxY - f.height
        } else { // verplaatsen met snappen
            f.origin.x += dx; f.origin.y += dy
            if let t = near(f.minX, xs) { f.origin.x = t } else if let t = near(f.maxX, xs) { f.origin.x = t - f.width }
            if let t = near(f.minY, ys) { f.origin.y = t } else if let t = near(f.maxY, ys) { f.origin.y = t - f.height }
        }
        w.setFrame(f, display: true)
    }
    override func mouseUp(with e: NSEvent) { cam?.save() }

    override func menu(for e: NSEvent) -> NSMenu? {
        guard let c = cam else { return nil }
        let m = NSMenu()
        m.addItem(NSMenuItem(title: c.device.localizedName, action: nil, keyEquivalent: ""))
        m.addItem(Act("Spiegelen", c.mirror) { c.mirror.toggle() })
        m.addItem(Act("Passend (balken i.p.v. bijsnijden)", c.fit) { c.fit.toggle() })
        m.addItem(.separator())
        for wd in [240.0, 400.0, 640.0] {
            m.addItem(Act("Breedte \(Int(wd))") {
                let f = c.panel.frame, h = wd * f.height / f.width
                c.panel.setFrame(NSRect(x: f.minX, y: f.maxY - h, width: wd, height: h), display: true); c.save()
            })
        }
        m.addItem(.separator())
        m.addItem(Act("Sluiten") { app.toggle(c.device) })
        return m
    }
}

final class Cam: NSObject {
    let id: String, device: AVCaptureDevice
    let session = AVCaptureSession()
    let panel: CamPanel, view: CamView
    var mirror: Bool { get { D.bool(forKey: "mirror.\(id)") } set { D.set(newValue, forKey: "mirror.\(id)"); apply() } }
    var fit: Bool { get { D.bool(forKey: "fit.\(id)") } set { D.set(newValue, forKey: "fit.\(id)"); apply() } }

    init(_ d: AVCaptureDevice) {
        device = d; id = d.uniqueID
        let dim = CMVideoFormatDescriptionGetDimensions(d.activeFormat.formatDescription)
        let ar = dim.height > 0 ? CGFloat(dim.width) / CGFloat(dim.height) : 16 / 9
        var fr = NSRect(x: 0, y: 0, width: 320, height: 320 / ar)
        if let s = D.string(forKey: "frame.\(d.uniqueID)") { fr = NSRectFromString(s) }
        else if let v = NSScreen.main?.visibleFrame {
            let o = CGFloat(app.cams.count) * 40
            fr.origin = NSPoint(x: v.maxX - fr.width - o, y: v.maxY - fr.height - o)
        }
        panel = CamPanel(contentRect: fr, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        view = CamView(frame: NSRect(origin: .zero, size: fr.size))
        super.init()
        panel.level = .floating
        panel.hasShadow = false
        panel.isOpaque = true
        panel.backgroundColor = .black
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.ignoresMouseEvents = D.bool(forKey: "locked")
        panel.contentView = view
        view.cam = self
        if let i = try? AVCaptureDeviceInput(device: d), session.canAddInput(i) { session.addInput(i) }
        view.preview.session = session
        apply()
        panel.orderFrontRegardless()
        DispatchQueue.global(qos: .userInitiated).async { [session] in session.startRunning() }
    }
    func apply() {
        CATransaction.begin(); CATransaction.setDisableActions(true)
        view.preview.transform = CATransform3DMakeScale(mirror ? -1 : 1, 1, 1)
        view.preview.videoGravity = fit ? .resizeAspect : .resizeAspectFill
        CATransaction.commit()
    }
    func save() { D.set(NSStringFromRect(panel.frame), forKey: "frame.\(id)") }
    func stop() {
        DispatchQueue.global().async { [session] in session.stopRunning() }
        panel.orderOut(nil)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var cams: [String: Cam] = [:]
    var item: NSStatusItem!
    var openIDs: [String] { get { D.stringArray(forKey: "open") ?? [] } set { D.set(newValue, forKey: "open") } }

    func applicationDidFinishLaunching(_ n: Notification) {
        allowScreenCaptureDevices()
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "web.camera", accessibilityDescription: "Spiegeltjes")
        let m = NSMenu(); m.delegate = self; item.menu = m
        let nc = NotificationCenter.default
        nc.addObserver(forName: AVCaptureDevice.wasConnectedNotification, object: nil, queue: .main) { [weak self] _ in self?.restore() }
        nc.addObserver(forName: AVCaptureDevice.wasDisconnectedNotification, object: nil, queue: .main) { [weak self] n in
            if let d = n.object as? AVCaptureDevice, let c = self?.cams.removeValue(forKey: d.uniqueID) { c.stop() }
        }
        AVCaptureDevice.requestAccess(for: .video) { _ in DispatchQueue.main.async { self.restore() } }
    }
    // Wat open stond komt terug, ook als een iPhone later pas verschijnt
    func restore() {
        for d in devices() where openIDs.contains(d.uniqueID) && cams[d.uniqueID] == nil { cams[d.uniqueID] = Cam(d) }
    }
    func toggle(_ d: AVCaptureDevice) {
        if let c = cams.removeValue(forKey: d.uniqueID) { c.stop(); openIDs.removeAll { $0 == d.uniqueID } }
        else { cams[d.uniqueID] = Cam(d); openIDs.append(d.uniqueID) }
    }
    func snapTargets(excluding w: NSWindow) -> ([CGFloat], [CGFloat]) {
        var xs: [CGFloat] = [], ys: [CGFloat] = []
        for s in NSScreen.screens { for f in [s.frame, s.visibleFrame] { xs += [f.minX, f.maxX]; ys += [f.minY, f.maxY] } }
        for c in cams.values where c.panel !== w { let f = c.panel.frame; xs += [f.minX, f.maxX]; ys += [f.minY, f.maxY] }
        return (xs, ys)
    }
    func menuNeedsUpdate(_ m: NSMenu) {
        m.removeAllItems()
        for d in devices() { m.addItem(Act(d.localizedName, cams[d.uniqueID] != nil) { [weak self] in self?.toggle(d) }) }
        m.addItem(.separator())
        m.addItem(Act("Vastzetten (klikken gaan erdoorheen)", D.bool(forKey: "locked")) { [weak self] in
            let l = !D.bool(forKey: "locked"); D.set(l, forKey: "locked")
            self?.cams.values.forEach { $0.panel.ignoresMouseEvents = l }
        })
        m.addItem(.separator())
        m.addItem(NSMenuItem(title: "Stoppen", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }
}

NSApplication.shared.setActivationPolicy(.accessory)
NSApplication.shared.delegate = app
NSApplication.shared.run()

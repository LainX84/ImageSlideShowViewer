"""Accelerazione GPU del visualizzatore e dello slideshow.

Il disegno delle immagini può passare per OpenGL invece che per la CPU:
  * "gl"      OpenGL della scheda video, cioè il driver NVIDIA / AMD / Intel;
  * "gl_soft" OpenGL software (Mesa llvmpipe, open source, incluso in PySide6):
              utile solo se il driver della scheda video dà problemi;
  * "cpu"     nessuna accelerazione (il metodo delle versioni precedenti);
  * "auto"    OpenGL della scheda video se disponibile, altrimenti CPU.

Con OpenGL l'immagine viene caricata una volta sola nella memoria della scheda video
come texture con mipmap: l'adattamento alla finestra, lo zoom e lo spostamento li fa
la GPU (filtro trilineare), senza ricalcolare l'immagine ridimensionata sulla CPU a
ogni cambio di dimensione, di zoom o di fotogramma (GIF/WebP animate).

La scelta del backend va fatta prima di creare QApplication (configure()).
"""
import struct

from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtGui import QImage

MODES = ("auto", "gl", "gl_soft", "cpu")

_mode = "auto"
_info = None        # risultato di probe(): dict oppure False


def mode_names():
    from .i18n import tr
    return [tr("Automatico (GPU se disponibile)"),
            tr("GPU – OpenGL della scheda video (NVIDIA / AMD / Intel)"),
            tr("OpenGL software (Mesa llvmpipe, open source)"),
            tr("Solo CPU (nessuna accelerazione)")]


def configure(settings):
    """Da chiamare PRIMA di creare QApplication."""
    global _mode
    m = str(settings.value("gpu/render", "auto"))
    _mode = m if m in MODES else "auto"
    A = Qt.ApplicationAttribute
    # più finestre (visualizzatori, slideshow doppio) condividono le texture
    QCoreApplication.setAttribute(A.AA_ShareOpenGLContexts)
    if _mode == "gl":
        QCoreApplication.setAttribute(A.AA_UseDesktopOpenGL)
    elif _mode == "gl_soft":
        QCoreApplication.setAttribute(A.AA_UseSoftwareOpenGL)


def mode():
    return _mode


def probe():
    """Prova a creare un contesto OpenGL. Ritorna un dict con renderer, versione e
    dimensione massima delle texture, oppure False. Il risultato resta in cache."""
    global _info
    if _info is not None:
        return _info
    _info = False
    if _mode == "cpu":
        return _info
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        ctx = QOpenGLContext()
        if not ctx.create():
            return _info
        surf = QOffscreenSurface()
        surf.setFormat(ctx.format())
        surf.create()
        if not ctx.makeCurrent(surf):
            return _info
        f = ctx.functions()
        renderer = f.glGetString(0x1F01) or ""     # GL_RENDERER
        version = f.glGetString(0x1F02) or ""      # GL_VERSION
        vendor = f.glGetString(0x1F00) or ""       # GL_VENDOR
        try:
            max_tex = int(f.glGetIntegerv(0x0D33))  # GL_MAX_TEXTURE_SIZE
        except Exception:  # noqa: BLE001
            max_tex = 4096
        fmt = ctx.format()
        ctx.doneCurrent()
        surf.destroy()
        low = renderer.lower()
        _info = {
            "renderer": renderer, "version": version, "vendor": vendor,
            "max_texture": max(1024, max_tex),
            "gl": (fmt.majorVersion(), fmt.minorVersion()),
            "software": any(k in low for k in ("llvmpipe", "softpipe", "swiftshader",
                                               "software", "gdi generic")),
            "gles": ctx.isOpenGLES(),
        }
    except Exception:  # noqa: BLE001 - nessun OpenGL utilizzabile
        _info = False
    return _info


def enabled():
    """True se il visualizzatore deve disegnare con OpenGL."""
    if _mode == "cpu":
        return False
    info = probe()
    if not info or info["gl"] < (2, 0):
        return False
    # in automatico l'OpenGL software non conviene: è più lento del disegno su CPU
    return not (_mode == "auto" and info["software"])


def description():
    """Testo per le opzioni: cosa si sta usando adesso."""
    from .i18n import tr
    if not enabled():
        info = probe() if _mode != "cpu" else False
        if _mode == "cpu":
            return tr("In uso: CPU (accelerazione disattivata)")
        if info and info["software"]:
            return tr("In uso: CPU (c'è solo OpenGL software: {r})", r=info["renderer"])
        return tr("In uso: CPU (OpenGL non disponibile)")
    info = probe()
    return tr("In uso: OpenGL {v} – {r}", v=info["version"].split(" ")[0], r=info["renderer"])


def prepare_image(img):
    """Converte (nel thread di caricamento) nel formato che la GPU riceve senza copie."""
    # _info già calcolato nel thread dell'interfaccia: qui non si crea nessun contesto
    if img is None or img.isNull() or _info is None or not enabled():
        return img
    if img.format() != QImage.Format.Format_RGBA8888:
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    return img


# --------------------------------------------------------------------- renderer
_VS = """
attribute highp vec2 pos;
attribute highp vec2 uv;
varying highp vec2 v_uv;
void main() {
    v_uv = uv;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FS = """
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D tex;
uniform highp vec2 px;      // un pixel dello schermo in coordinate texture (0 = ingrandimento)
varying highp vec2 v_uv;
void main() {
    // riduzione: 4 campioni dentro il pixel (oltre alle mipmap) = niente moiré sui dettagli fini
    highp vec2 d = px * 0.25;
    vec4 c = (texture2D(tex, v_uv + vec2(-d.x, -d.y)) + texture2D(tex, v_uv + vec2(d.x, -d.y)) +
              texture2D(tex, v_uv + vec2(-d.x, d.y)) + texture2D(tex, v_uv + vec2(d.x, d.y))) * 0.25;
    // colore premoltiplicato: le parti trasparenti lasciano vedere lo sfondo
    gl_FragColor = vec4(c.rgb * c.a, c.a);
}
"""

GL_FLOAT = 0x1406
GL_TRIANGLE_STRIP = 0x0005
GL_COLOR_BUFFER_BIT = 0x4000
GL_TEXTURE0 = 0x84C0
GL_BLEND = 0x0BE2
GL_ONE = 1
GL_ONE_MINUS_SRC_ALPHA = 0x0303


class TextureRenderer:
    """Disegna QImage come texture con mipmap (da usare dentro paintGL, con il contesto attivo)."""

    MAX_TEXTURES = 6

    def __init__(self):
        from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram
        self.ok = False
        self.textures = {}          # cacheKey -> (QOpenGLTexture, QSize originale)
        self.order = []
        self.prog = QOpenGLShaderProgram()
        V, F = QOpenGLShader.ShaderTypeBit.Vertex, QOpenGLShader.ShaderTypeBit.Fragment
        if not (self.prog.addShaderFromSourceCode(V, _VS)
                and self.prog.addShaderFromSourceCode(F, _FS) and self.prog.link()):
            return
        self.loc_pos = self.prog.attributeLocation("pos")
        self.loc_uv = self.prog.attributeLocation("uv")
        self.loc_tex = self.prog.uniformLocation("tex")
        self.loc_px = self.prog.uniformLocation("px")
        self.vbo = QOpenGLBuffer()
        if not self.vbo.create():
            return
        self.vbo.bind()
        self.vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.DynamicDraw)
        self.vbo.allocate(bytes(64), 64)
        self.vbo.release()
        info = probe() or {}
        self.max_tex = info.get("max_texture", 4096)
        self.ok = True

    def texture(self, img):
        from PySide6.QtOpenGL import QOpenGLTexture
        key = img.cacheKey()
        hit = self.textures.get(key)
        if hit is not None:
            self.order.remove(key)
            self.order.append(key)
            return hit[0]
        src = img
        if img.width() > self.max_tex or img.height() > self.max_tex:
            # oltre il limite della scheda video: si riduce prima sulla CPU
            src = img.scaled(self.max_tex, self.max_tex, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        if src.format() != QImage.Format.Format_RGBA8888:
            src = src.convertToFormat(QImage.Format.Format_RGBA8888)
        tex = QOpenGLTexture(src, QOpenGLTexture.MipMapGeneration.GenerateMipMaps)
        tex.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
        tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self.textures[key] = (tex, QSize(img.size()))
        self.order.append(key)
        while len(self.order) > self.MAX_TEXTURES:
            old = self.order.pop(0)
            t, _s = self.textures.pop(old)
            t.destroy()
        return tex

    def draw(self, f, img, rect, vw, vh, smooth=True):
        """Disegna img nel rettangolo rect (pixel del dispositivo, origine in alto a sinistra)
        di una superficie vw×vh."""
        from PySide6.QtOpenGL import QOpenGLTexture
        tex = self.texture(img)
        tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear if smooth
                                   else QOpenGLTexture.Filter.Nearest)
        x0 = 2.0 * rect.left() / vw - 1.0
        x1 = 2.0 * rect.right() / vw - 1.0
        y0 = 1.0 - 2.0 * rect.top() / vh
        y1 = 1.0 - 2.0 * rect.bottom() / vh
        data = struct.pack("16f",
                           x0, y1, 0.0, 1.0,
                           x1, y1, 1.0, 1.0,
                           x0, y0, 0.0, 0.0,
                           x1, y0, 1.0, 0.0)
        self.prog.bind()
        self.vbo.bind()
        self.vbo.write(0, data, len(data))
        self.prog.enableAttributeArray(self.loc_pos)
        self.prog.enableAttributeArray(self.loc_uv)
        self.prog.setAttributeBuffer(self.loc_pos, GL_FLOAT, 0, 2, 16)
        self.prog.setAttributeBuffer(self.loc_uv, GL_FLOAT, 8, 2, 16)
        f.glActiveTexture(GL_TEXTURE0)
        tex.bind()
        self.prog.setUniformValue1i(self.loc_tex, 0)
        rw, rh = max(1.0, rect.width()), max(1.0, rect.height())
        minify = rw < img.width() or rh < img.height()
        self.prog.setUniformValue(self.loc_px, *( (1.0 / rw, 1.0 / rh) if minify else (0.0, 0.0)))
        f.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        tex.release()
        self.prog.disableAttributeArray(self.loc_pos)
        self.prog.disableAttributeArray(self.loc_uv)
        self.vbo.release()
        self.prog.release()

    def destroy(self):
        for t, _s in self.textures.values():
            t.destroy()
        self.textures.clear()
        self.order.clear()
        if self.ok:
            self.vbo.destroy()


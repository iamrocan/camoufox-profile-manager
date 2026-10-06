# Generate a .ico (orange fox on dark background) for the launcher.
# Uses System.Drawing + Segoe UI Emoji; packs a 256x256 PNG into an .ico container.

Add-Type -AssemblyName System.Drawing

$outIco = Join-Path $PSScriptRoot 'camoufox.ico'
$size   = 256

$bmp = New-Object System.Drawing.Bitmap $size, $size
$g   = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode     = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality

# Dark rounded background
$bg = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 26, 26, 26))
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$r = 40
$path.AddArc(0, 0, $r*2, $r*2, 180, 90)
$path.AddArc($size - $r*2, 0, $r*2, $r*2, 270, 90)
$path.AddArc($size - $r*2, $size - $r*2, $r*2, $r*2, 0, 90)
$path.AddArc(0, $size - $r*2, $r*2, $r*2, 90, 90)
$path.CloseFigure()
$g.FillPath($bg, $path)

# Subtle orange glow ring
$pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(60, 255, 140, 0)), 4
$g.DrawPath($pen, $path)

# Fox emoji centered
$font = New-Object System.Drawing.Font 'Segoe UI Emoji', 160, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
$sf = New-Object System.Drawing.StringFormat
$sf.Alignment     = [System.Drawing.StringAlignment]::Center
$sf.LineAlignment = [System.Drawing.StringAlignment]::Center
$fg = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
$rect = New-Object System.Drawing.RectangleF 0, 10, $size, $size
$g.DrawString([char]::ConvertFromUtf32(0x1F98A), $font, $fg, $rect, $sf)

$g.Dispose()

# Serialize PNG into memory
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $ms.ToArray()
$ms.Dispose()
$bmp.Dispose()

# Build .ico (one 256x256 PNG-encoded entry)
$fs = [System.IO.File]::Open($outIco, 'Create')
$bw = New-Object System.IO.BinaryWriter $fs
# ICONDIR
$bw.Write([UInt16]0)         # reserved
$bw.Write([UInt16]1)         # type: icon
$bw.Write([UInt16]1)         # count
# ICONDIRENTRY
$bw.Write([Byte]0)           # width (0 = 256)
$bw.Write([Byte]0)           # height (0 = 256)
$bw.Write([Byte]0)           # color count
$bw.Write([Byte]0)           # reserved
$bw.Write([UInt16]1)         # planes
$bw.Write([UInt16]32)        # bits per pixel
$bw.Write([UInt32]$png.Length)
$bw.Write([UInt32]22)        # offset = 6 + 16
# PNG payload
$bw.Write($png)
$bw.Flush()
$bw.Close()
$fs.Close()

Write-Output "Icon written: $outIco  ($($png.Length) bytes PNG inside)"

"""One-off generator for the committed fixture pages (kept so they can be regenerated)."""

import base64
import pathlib

d = pathlib.Path(__file__).parent / "fixtures" / "pages"
(d / "with_files_files").mkdir(parents=True, exist_ok=True)
head = (
    '<html><head><title>{t}</title>\r\n<script src="whver.js"></script></head>\r\n<body>\r\n'
    '<script>RH_Document_Write("<p>menu</p>");RH_AddMasterBreadcrumbs("index.htm","","Home","");</script>\r\n'
)


def w(name, title, body):
    (d / name).write_text(head.format(t=title) + body + "\r\n</body></html>", encoding="utf-8-sig", newline="")


w("tables.htm", "Tabellen voorbeeld",
  '<h1>Tabellen voorbeeld</h1><p class="MsoNormal">Uitleg bij de velden.</p>'
  '<h2>Velden</h2><table class="Table_Style_CN"><tr><td class="t1st">Veld</td><td>Uitleg</td></tr>'
  '<tr><td class="t1st">Naam</td><td>De naam van de <a href="no_sections.htm#a">debiteur</a></td></tr>'
  '<tr><td class="t1st">Bedrag</td><td>Het bedrag | in euro</td></tr></table>'
  '<h3>Lijst</h3><ul><li>Eerste punt</li><li>Tweede punt</li></ul>')
w("no_sections.htm", "Pagina zonder tussenkoppen",
  '<p class="MsoNormal"><b>Let op</b></p><p class="MsoNormal">Deze pagina heeft geen koppen. '
  'Zie ook <a href="tables.htm">Tabellen voorbeeld</a>.</p><p class="MsoNormal">Tweede alinea met tekst.</p>')
w("with_files.htm", "Pagina met afbeeldingen",
  '<h2>Schermen</h2><p><img src="with_files_files/pic.png" alt="x"><img src="images/shot.gif">'
  '<img src="missing.jpg"></p><p>Tekst na de afbeeldingen.</p>')
w("Mengcodes_voorbeeld.htm", "Mengcodes voorbeeld",
  '<h1>Mengcodes voorbeeld</h1><table class="MsoNormalTable"><tr><td>Omschrijving</td><td>Mengobject</td>'
  '<td>Mengveld</td><td>Mengcode</td></tr>'
  '<tr><td>Adres</td><td>agiro[1]</td><td>adresregel2</td><td>{$agiro[1].adresregel2}</td></tr>'
  '<tr><td>Plaats</td><td>agiro[1]</td><td>plaats</td><td>{$agiro[1].plaats}</td></tr></table>')
(d / "with_files_files" / "pic.png").write_bytes(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))

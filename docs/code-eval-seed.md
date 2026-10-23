# Seed questions for the Source Code evaluation

Real questions already answered from the Source Code, with the correct answer and the files that prove it. Collected for [#47](https://github.com/MikeTestor/navigate_helper/issues/47) as the start of the Evaluation Set for Code Answers (see [#44](https://github.com/MikeTestor/navigate_helper/issues/44)).

**No customer data.** No customer names, dossier numbers, amounts, dates of real runs or other production data. Keep the wording of the question, but replace anything specific with a neutral example.

Aim for 8–10 entries covering all three types:

- **Manual wrong**: the Manual says something the code contradicts.
- **Manual silent**: the Manual does not cover it.
- **Manual and code agree**: the Manual is correct.

## Entry template

Copy this block for each question.

```md
## N. <short title>

- **Type:** Manual wrong | Manual silent | Manual and code agree
- **Question:** <the question as a Helpdesk Employee would ask it, in Dutch>
- **Expected answer:** <the correct answer, in Dutch>
- **Proving files:** <path or path:line-range in the Source Code, for example ed/ep-11940.p>
- **Manual Page(s), if any:** <Manual Page file name(s), or "none">
```

## Entries

1 Kostenplaats
**Type:** 
Manual and code agree

**Question:** 
Wat is een kostenplaats

**Expected answer:**
 Een kostenplaats is binnen Aryza Navigate een administratieve indeling die wordt gebruikt om kosten te verdelen over de verschillende geledingen binnen de organisatie, bijvoorbeeld afdelingen van het kantoor (zoals Algemeen, Administratie, ICT, Incasso).

**Answer from code base (Claude in VS code with bsx14 foler)**
Dit is wat bfx14 laat zien. Ik heb alleen die bestanden gelezen. De definitie van een kostenplaats staat daar niet letterlijk in, dus een deel hieronder is afgeleid.

Wat de code laat zien

Een kostenplaats is een apart schema per administratie en boekjaar. In ab-14202_display.p worden de kostenplaatsen opgehaald uit tabel ab-142, met als sleutel cdadmin + boekjaar + kostenplaats. Het datamodel ab14202.cs heeft dezelfde sleutel (BoekJaar, Admin, kostenplaats). Elke administratie heeft dus per boekjaar zijn eigen lijst kostenplaatsen. Dit is waarschijnlijk het onderhoudsscherm voor het kostenplaatsschema.

Een kostenplaats staat naast een kostendrager. Bijna overal komen de twee samen voor. In ab.xml hebben boekingsregels de velden kostenplaats en kostendrager als sleutel. Er zijn aparte schermen voor kostenplaats (ab16251) en kostendrager (ab16231), en per kostenplaats kun je kostendragers en grootboekrekeningen (GrbRekNr) onderscheiden.

Een kostenplaats hoort bij een boeking. In aa-27102_save.p krijgt een verbijzonderingsregel (ab-161) bij het opslaan kostenplaats en kostendrager mee. Die regel hangt aan een boekingsregel (ab-149) en heeft ook een grootboekrekening, bedrag en aantal. Een boekingsregel kan dus over kostenplaats/kostendrager worden verdeeld (verbijzondering).

Het schema is een apart onderdeel van de administratie. In abkop04.xaml.cs zijn "Kostenplaatsschema", "Kostendragerschema" en "Standaardverdelingen" aparte vinkjes. Ze zijn gekoppeld: kostendragerschema aanvinken vinkt kostenplaatsschema aan, en standaardverdelingen ook. Een kostendrager of standaardverdeling kan dus niet bestaan zonder kostenplaatsschema. Het scherm lijkt een kopieerfunctie, maar dat heb ik niet bevestigd.

Wat ik niet weet

Ik heb de tabelomschrijving (.df) en de helpteksten niet gelezen. Daar staat waarschijnlijk wat bfx14 er officieel onder verstaat.
Dat een kostenplaats een afdeling of project is, volgt niet uit deze code.
Wat de tabellen ab-142 en ab-161 precies bevatten, heb ik niet gecontroleerd. Dat leid ik af uit de gebruikte veldnamen.
Zal ik de tabeldefinitie van ab-142 en ab-161 opzoeken, of de help- en veldlabels?

**Proving files:**
see the mentioned programs above
 
**Manual Page(s), if any:** <Manual Page file name(s), or "none">
Kostenplaatsen

2 Rentestop
**Type:** 
Manual does not know. Code gives the right answer.

**Question:** 

Is er, naast het handmatig erin zetten, een andere manier is om op meerdere dossiers een rentestop in te zetten?

**Expected answer:**
 Ja, er is een programma met de naam updrentestop.p.

**Answer from code base (Claude in VS code with bsx14 foler)**
Ja, er is een bulkroute: een CSV-import via het bestand-import-mechanisme (hp). Ik heb de code gelezen. Ik heb het niet uitgeprobeerd, en de inrichting op jullie omgeving heb ik niet kunnen controleren.

Hoe het werkt

hp-dispatch.p pakt .csv-bestanden op uit de map X, onder de map die bij de directory-code HPIMPU hoort (in tabel ed-003).
De bestandsnaam bepaalt welke handler het bestand verwerkt: alles vóór de eerste _. Voor rentestop is dat dus een bestand dat begint met updrentestop_, bijvoorbeeld updrentestop_20261022.csv.
De handler is updrentestop.p. Hij zet per regel de rentestop aan of uit op alle ep-110-records (de rentegegevens) van dat hoofddossier. Elke wijziging komt in het wijzigingslog.
Na verwerking verhuist het bestand naar map S (gelukt) of E (fout). Het logbestand komt in map L.
Opbouw van een regel

De regel wordt als CSV gelezen met 6 verplichte velden:

Veld	Inhoud
3	administratiecode (cdadmin)
4	hoofddossiernummer (cd_hfdmapnr)
5	rentestop ja/nee
6	rente boeken ja/nee
Velden 1 en 2 gebruikt de handler niet. Ik heb niet nagekeken wat daar normaal in staat; ik neem aan dat het de generieke kolommen van het hp-formaat zijn. Controleer dat aan de hand van een bestaand voorbeeldbestand.

Wat "rente boeken" doet

Bij rentestop = ja én rente boeken = ja wordt eerst de opgebouwde rente tot vandaag geboekt (boekingscode 900001).
Daarna wordt de rentestop gezet en wordt dd_rblbij (de datum tot waar rente is berekend) verhoogd naar vandaag.
Dossiers met cd_mapkverw = '9' (in opbouw) krijgen geen renteboeking.
Andere routes die ik tegenkwam

Automatisch: ec-alg00.p zet rentestop bij CJIB-dossiers via PriInterestStopDossier. Bij onbevoegd kan het ook automatisch (l_AutoRenteStop). Dat gebeurt op basis van een gebeurtenis, niet op jouw selectie.
Eenmalig: hs-fixrstp.p is een eenmalig fixprogramma voor een specifieke klant (CN-21572). Niet geschikt als algemene bulkroute.
Waar je op moet letten

De handler moet gecompileerd aanwezig zijn als hp/handlers/updrentestop.r. Anders komt het bestand in E.
De dispatcher moet draaien en HPIMPU moet ingericht zijn. Check dat met applicatiebeheer.
Zet eerst een kleine testset door, want een fout in een regel stopt de rest niet automatisch en het wijzigingslog is je enige terugweg.
Zal ik een voorbeeld-CSV voor je maken of de regelopbouw nog preciezer uitzoeken (bijvoorbeeld met hp-tools.i)?

**Proving files:**
updrentestop.p 
 
**Manual Page(s), if any:** <Manual Page file name(s), or "none">
none

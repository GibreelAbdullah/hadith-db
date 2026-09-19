# OpenITI source files (mARkdown)

Downloaded from the OpenITI RELEASE corpus. Re-download with the URLs below.
Metadata index: OpenITI/kitab-metadata-automation → kitab_metadata_for_DLME_latest_release.tsv

| collection      | version_uri                                   | text_url |
|-----------------|-----------------------------------------------|----------|
| bayhaqi_kubra   | 0458Bayhaqi.SunanKubra.JK000484-ara1          | https://raw.githubusercontent.com/openiti/release/master/data/0458Bayhaqi/0458Bayhaqi.SunanKubra/0458Bayhaqi.SunanKubra.JK000484-ara1 |
| ibn_khuzayma    | 0311IbnKhuzaymaNaysaburi.Sahih.JK000132-ara1  | https://raw.githubusercontent.com/openiti/release/master/data/0311IbnKhuzaymaNaysaburi/0311IbnKhuzaymaNaysaburi.Sahih/0311IbnKhuzaymaNaysaburi.Sahih.JK000132-ara1 |
| ibn_abi_shayba  | 0235IbnAbiShayba.Musannaf.JK000786-ara1       | https://raw.githubusercontent.com/openiti/release/master/data/0235IbnAbiShayba/0235IbnAbiShayba.Musannaf/0235IbnAbiShayba.Musannaf.JK000786-ara1.completed |
| tabarani_kabir  | 0360Tabarani.MucjamKabir.Shamela0001733-ara1  | https://raw.githubusercontent.com/openiti/release/master/data/0360Tabarani/0360Tabarani.MucjamKabir/0360Tabarani.MucjamKabir.Shamela0001733-ara1 |
| tabarani_awsat  | 0360Tabarani.MucjamAwsat.JK000883-ara1        | https://raw.githubusercontent.com/openiti/release/master/data/0360Tabarani/0360Tabarani.MucjamAwsat/0360Tabarani.MucjamAwsat.JK000883-ara1 |
| mustadrak       | 0405HakimNaysaburi.Mustadrak.JK000467-ara1    | https://raw.githubusercontent.com/openiti/release/master/data/0405HakimNaysaburi/0405HakimNaysaburi.Mustadrak/0405HakimNaysaburi.Mustadrak.JK000467-ara1 |
| shuab_iman      | 0458Bayhaqi.ShucabIman.Shamela0010660-ara1    | https://raw.githubusercontent.com/OpenITI/0475AH/master/data/0458Bayhaqi/0458Bayhaqi.ShucabIman/0458Bayhaqi.ShucabIman.Shamela0010660-ara1 |
| daraqutni       | 0385Daraqutni.Sunan.JK000477-ara1             | https://raw.githubusercontent.com/openiti/release/master/data/0385Daraqutni/0385Daraqutni.Sunan/0385Daraqutni.Sunan.JK000477-ara1.completed |
| abu_yala        | 0307AbuYaclaMawsili.Musnad.JK000485-ara1      | https://raw.githubusercontent.com/openiti/release/master/data/0307AbuYaclaMawsili/0307AbuYaclaMawsili.Musnad/0307AbuYaclaMawsili.Musnad.JK000485-ara1 |
| tayalisi        | 0204AbuDawudTayalisi.Musnad.JK000470-ara1     | https://raw.githubusercontent.com/openiti/release/master/data/0204AbuDawudTayalisi/0204AbuDawudTayalisi.Musnad/0204AbuDawudTayalisi.Musnad.JK000470-ara1 |
| jami_saghir     | 0911Suyuti.JamicSaghir.Shia002261Vols-ara1    | https://raw.githubusercontent.com/openiti/release/master/data/0911Suyuti/0911Suyuti.JamicSaghir/0911Suyuti.JamicSaghir.Shia002261Vols-ara1 |

## Bespoke converters

Most collections convert with `openiti_convert.py`. Two use dedicated parsers
because their source format differs:

- **jami_saghir** → `jami_saghir_convert.py` (inline `N - ` hadith markers,
  alphabetical letter sections).
- **tabarani_kabir** → `tabarani_kabir_convert.py` (Shamela edition: `### | N -`
  hadith markers with text on the following `#` lines; one book per Companion,
  sub-topics as chapters). Chosen over the JK000474 edition because it is more
  complete (JK was missing hadith, e.g. Wa'il b. Hujr) and cleanly structured.
- **shuab_iman** → `shuab_iman_convert.py` (Shamela ط الرشد edition,
  Shamela0010660, matching shamela.ws/book/10660: `#`-level "N من شعب الإيمان"
  branch headers -> books; `### |` باب/فصل -> chapters; `### | N -` hadith with
  text on following `#` lines). Chosen over the JK000021 (Dar al-Kutub
  al-Ilmiyya) edition to match the Shamela section layout.

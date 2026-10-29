return {--do NOT change this line
 -- Kopirati u <koreader>/news/feed_config.lua na Boox-u (obično /sdcard/koreader/news/).

 -- Sažeci opiniona: teza, argumenti, zaključak (iz feed-a, bez skidanja originala)
 { "https://drcolosso42.github.io/boox-vesti/opinioni.xml", limit = 40, max_age = "2d", download_full_article=false, include_images=false },

 -- Isti opinioni, ceo originalni tekst (KOReader ga skida sa sajta)
 { "https://drcolosso42.github.io/boox-vesti/originali.xml", limit = 40, max_age = "2d", download_full_article=true, include_images=false, enable_filter=true, filter_element = "" },

 -- Digest vesti po događaju
 { "https://drcolosso42.github.io/boox-vesti/vesti.xml", limit = 3, max_age = "2d", download_full_article=false, include_images=false },

}--do NOT change this line

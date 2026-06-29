import * as pagefind from "pagefind";
import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = join(__dirname, "data");

async function main() {
  const collectionsData = JSON.parse(readFileSync(join(DATA_DIR, "collections.json"), "utf-8"));

  const { index } = await pagefind.createIndex({ forceLanguage: "en" });

  let totalIndexed = 0;

  for (const coll of collectionsData.collections) {
    const metaPath = join(DATA_DIR, coll.short_name, "metadata.json");
    let meta;
    try {
      meta = JSON.parse(readFileSync(metaPath, "utf-8"));
    } catch {
      continue;
    }

    // Read text files for each language
    const textByLang = {};
    for (const lang of meta.languages) {
      try {
        textByLang[lang] = readFileSync(join(DATA_DIR, coll.short_name, `${lang}.txt`), "utf-8").split("\n");
      } catch {
        // Language file not available
      }
    }

    // Index each hadith
    for (const rec of meta.records) {
      if (rec.cat !== "hadith") continue;

      // Get text content from all languages
      const contentParts = [];
      for (const lang of meta.languages) {
        const lines = textByLang[lang];
        if (!lines) continue;
        const line = lines[rec.line] || "";
        // Strip "category|num|" prefix
        const secondPipe = line.indexOf("|", line.indexOf("|") + 1);
        const text = secondPipe !== -1 ? line.slice(secondPipe + 1) : line;
        // Strip HTML tags and unescape
        const clean = text.replace(/<[^>]*>/g, "").replace(/\\n/g, " ");
        if (clean) contentParts.push(clean);
      }

      if (contentParts.length === 0) continue;

      const collName = coll.en || coll.ar || coll.short_name;
      const book = meta.books.find(b => b.number === rec.book);
      const bookName = book ? (book.en || book.ar || `Book ${rec.book}`) : "";

      await index.addCustomRecord({
        url: `/${coll.short_name}:${rec.num}`,
        content: contentParts.join(" "),
        language: "en",
        meta: {
          title: `${collName} : ${rec.num}`,
          collection: collName,
          book: bookName,
          hadith_num: rec.num || "",
          collection_short: coll.short_name,
        },
        filters: {
          collection: [coll.short_name],
        },
      });

      totalIndexed++;
    }

    console.log(`  ${coll.short_name}: indexed ${meta.records.filter(r => r.cat === "hadith").length} hadiths`);
  }

  console.log(`\nTotal indexed: ${totalIndexed}`);

  await index.writeFiles({ outputPath: join(DATA_DIR, "pagefind") });
  console.log("Pagefind index written to data/pagefind/");

  await pagefind.close();
}

main().catch(console.error);

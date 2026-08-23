<contextual_retrieval_instructions>
  <purpose>
    Generate a concise factual context that makes one target chunk independently
    understandable and easier to retrieve with semantic search and BM25.
    The result will be prepended to the unchanged chunk before indexing.
  </purpose>

  <use_document_context>
    Use the overall document only to situate and disambiguate the target chunk.
    Resolve implicit references when the source supports the resolution, including
    entities, pronouns, policies, reports, periods, products, systems, departments,
    technologies, versions, and business concepts.
  </use_document_context>

  <retrieval_rules>
    Preserve important searchable names, acronyms, identifiers, dates, technical
    terms, product names, system names, policy names, report periods, and business
    entities exactly when supported by the supplied source.
    Be specific to this chunk. Avoid generic statements that could describe every
    chunk in the document. Do not summarize the whole document, unnecessarily
    repeat the chunk, rewrite the complete chunk, answer a question, analyze the
    source, infer unsupported facts, or add outside knowledge.
  </retrieval_rules>

  <output_rules>
    Return only one short contextual description, normally 50-100 tokens, as plain
    text. Do not use Markdown headings or prefixes such as Document:, Section:,
    Context:, or Description:.
  </output_rules>
</contextual_retrieval_instructions>

<document_title>{{document_title}}</document_title>
<section_path>{{section_path}}</section_path>
<document>
{{document_context}}
</document>
<chunk>
{{chunk_text}}
</chunk>

# Navigate Helper

An assistant that answers questions about the application Aryza Navigate, grounded in its online Manual and, when the Manual is wrong or silent, in the application's Source Code.

## Language

### People

**Asker**:
Whoever types a question into the assistant. For now always a Helpdesk Employee; later possibly an End User.
_Avoid_: User (ambiguous with End User)

**Helpdesk Employee**:
An Aryza employee who supports customers of Navigate and can judge whether an answer is correct.
_Avoid_: Agent, support user

**End User**:
Someone at a customer organisation who works in Navigate itself.
_Avoid_: Client, customer user

### Knowledge

**Manual**:
The complete online help of Aryza Navigate, written in Dutch, as exported from RoboHelp.
_Avoid_: Docs, knowledge base, wiki

**Manual Page**:
One `.htm` file of the Manual, covering a single topic.
_Avoid_: Document, file, topic

**Kennispagina**:
A curated single-page wrapper around the Manual on the shared drive, covering about 20 topics with text taken from Manual Pages and rebranded from "Credit Navigator" to "Aryza Navigate". It is not a source for Answers.
_Avoid_: Online helpdesk, online manual

**Cleaned Page**:
The Markdown version of one Manual Page, keeping its headings, lists, tables, Screenshots and Page Links, with RoboHelp boilerplate removed.
_Avoid_: Processed file, clean text

**Screenshot**:
An image embedded in a Manual Page. It is shown alongside an answer but is not itself searched.
_Avoid_: Image, picture

**Page Link**:
A reference from one Manual Page to another Manual Page.
_Avoid_: Hyperlink, URL

**Section**:
A part of a Manual Page that starts at a heading and runs to the next heading of the same or a higher level. Chunks are cut from Sections.
_Avoid_: Paragraph, block

**Chunk**:
A contiguous piece of a Manual Page, remembering which Manual Page, Screenshots and Page Links it came from.
_Avoid_: Snippet, passage, fragment

### Source Code

**Source Code**:
The application source of Aryza Navigate, the authoritative record of how the application behaves. Where the Manual and the Source Code disagree, the Source Code is right.
_Avoid_: The repo, bfx14

**Code Checkout**:
The read-only copy of the Source Code that the assistant searches. It is never part of this project's own repository.
_Avoid_: Code base copy, mirror

**Code Search**:
The investigation of the Source Code that produces a Code Answer, reading files the way a developer would. Nothing is chunked or indexed.
_Avoid_: Code retrieval, code index

**Code Citation**:
A reference to a file and line range in the Code Checkout, shown with a short snippet. It is to a Code Answer what a Cited Chunk is to a Manual Answer.
_Avoid_: Code source, code reference

### Answering

**Answer**:
Either a Manual Answer or a Code Answer.
_Avoid_: Response, reply

**Manual Answer**:
The assistant's Dutch reply to an Asker's question, written only from Retrieved Chunks and accompanied by the Screenshots and Page Links of its Cited Chunks.
_Avoid_: Response, reply

**Code Answer**:
The assistant's Dutch reply to an Asker's question, written from a Code Search. It carries Code Citations, says whether it agrees with the Manual Answer, states what it could not check, and is labelled unverified. Identifiers and code stay as written.
_Avoid_: Developer answer, technical answer

**Retrieved Chunk**:
A Chunk selected as possibly relevant to a question and given to the LLM.
_Avoid_: Hit, result, context

**Cited Chunk**:
A Retrieved Chunk that the Answer explicitly says it was based on. Only Cited Chunks contribute Screenshots and Page Links to an Answer.
_Avoid_: Source, reference

**Evaluation Set**:
A collection of real helpdesk questions, each paired with the Manual Page(s) that answer it, used to judge Answer quality.
_Avoid_: Test set, benchmark

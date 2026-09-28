# Starting a Middle-Large Project with Matt Pocock's Skills

**Case study: a RAG-based helpdesk tool**

## The question

For a middle-large project, should I use `/grill-with-docs` or another skill first? I think there are more skills that can help with preparing the layout of a project.

I'm planning to create a helpdesk tool where helpdesk employees can ask questions about a certain application in a user interface. The data is in a vector database, so essentially it's a RAG project. It's divided into five parts:

- Clean the files so they can be chunked
- Make chunks
- Embed in a vector DB
- Test the result and modify (chunk size, for example)
- Create the user interface

I'll create this app in a separate chat session. How should I start? Should I create instructions in an `.md` file and then start a session with `/grill-with-docs`, adding that file? Or should I do other things — start other skills first, and maybe other skills after as well?

## The recommendation

Given the size and shape of this project (multiple distinct phases, genuinely new project, uncertain technical decisions in a couple of spots), start one step earlier than `/grill-with-docs`.

### 1. Settle the location first

Is this new RAG tool going in a brand-new folder outside `bfx14`, or nested as another `projects\<name>\` folder inside `bfx14`?

If it's a new top-level folder, run `/mattpocock-skills:setup-matt-pocock-skills` there once first — per-repo config (issue tracker, domain docs) doesn't carry over automatically to a separate folder.

### 2. Start with `/mattpocock-skills:wayfinder`, not `/grill-with-docs`

Its whole purpose: *"Plan a huge chunk of work, more than one agent session can hold, as a shared map of decision tickets, and resolve them one at a time."*

Five phases with several open design questions is exactly the "too big for one grilling session" case this is built for. `/grill-with-docs` is better suited to one focused decision/plan, not a multi-phase build like this.

### 3. Within that map, lean on two more skills for the specific uncertain spots

| Skill | When to use it |
|---|---|
| `/mattpocock-skills:prototype` | For technical unknowns — matches the "test the result and modify (chunk size for example)" phase almost exactly. Built to answer a design question with throwaway code you validate and discard. |
| `/mattpocock-skills:grill-with-docs` | For sharpening each phase's plan and building up the domain glossary (`CONTEXT.md`) as decisions get made — used per-phase rather than for the whole project at once. |

### 4. Once a phase is settled

```
/mattpocock-skills:to-spec  →  /mattpocock-skills:to-tickets  →  /mattpocock-skills:implement  →  /mattpocock-skills:code-review
```

Same main flow as any other piece of work.

### On writing an `.md` brief first

Good instinct — keep doing that. A short phase breakdown (like the five bullets above) is already a solid starting brief. Reference it with `@filename` when kicking off `/mattpocock-skills:wayfinder`.

### For moments of doubt

`/mattpocock-skills:ask-matt` — its whole job is "which skill fits this situation." Use it any time you're unsure mid-project which skill to reach for.

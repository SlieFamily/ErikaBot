# Project conventions

- Prefer the installed NoneBot adapter's message factories, `Bot` API methods and existing plugins before writing integration code. Check the local implementations and official documentation first.
- For QQ extensions that the standard adapter does not explicitly declare, use NoneBot's existing dynamic `Bot` API dispatch with documented action names. Avoid a separate HTTP client or recreating NapCat/QQ protocol internals when the framework already supports the capability. Only fall back after verifying that no suitable existing interface is available, and document the reason.
- Keep the running bot connected during investigation and tests. Develop and test in an isolated copy; restart the production bot only when deploying a verified change. Preserve DSH sessions and unrelated runtime data.
- Model output is untrusted. Validate recipients and message IDs against observed messages in the same allowed chat, bound optional actions, and never interpret arbitrary CQ text as executable segments.

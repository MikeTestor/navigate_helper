# Navigate helper project

There is an online manual for the application Aryza Navigate. To help users and also employees at the helpdesk, an application will be developed where AI will help to get the right answers when a user asks a question. For that the RAG technique will be used.

Five stages to build this entire project:
1. Prepare (clean) the files
2. Make chuncks
3. Embed in a vector DB
4. Test and refine
5. Create a user-interface


## 1 Prepare (clean) the files
The raw data can be:
* hmtl
* json
* txt
* md
* images

and a lot of other things. In the first stage the files will be cleaned and prepared for the chuncking. For example:
* in html files remove all the markup

The processed (cleaned) files will land in database/knowledge-base/cleaned

## 2 Make chuncks
Important decisions:
* what will the chunck size be
* what will the overlap size be
* what metadata will I need
* create a list of json files. Every chunk will be a json record with the actual text and some metadata
* every chunk will get an ID

The processed (chunked) files will land in database/knowledge-base/chunked

## 3 Embed in a vector DB
* choose your vector DB. Chroma for example
* choose tools for embedding. Langchain for example

For this project we will use Chroma and Langchain

## 4 Test and refine
for this I need a user-interface where I can ask questions and get answers. the answers should already have the matching images and links to certain other .htm pages when this is the case. Is Gradio the best technique during the development phase?

## 5 Create a user-interface
I am not sure yet if it will be created in Gradio or a more advanced front-end technique. In development phase I do not want to have to deploy it. With Gradio you don't have to deploy. Are there alternatives or is Gradio the way to go

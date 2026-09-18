# This is an example for a RAG project

Five stages:
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

The processed (chunked) files will land in database/knowledge-base/chuncked

## 3 Embed in a vector DB
* choose your vector DB. Chroma for example
* choose tools for embedding. Langchain for example
* 

## 4 Test and refine

## 5 Create a user-interface

# SQuAD_challenge

SQuAD is a reading comprehension dataset. The deep learning model will be given a paragraph, and a question about that paragraph, as input. The goal is to answer the question correctly

The model is consist of three layers:

- RNN Encoder Layer:
Use bi-directional GRU to encode context and question, and feed the states vector to the next layer.

- Attention Layer:
Use bi-directional-attention mechanism to calculate similarity matrix between context and question, and generate attention vector from both sides. The output in this layer is original context state plus context_to_question attention and question_to_context attention.

- Fully Connected Layer
Use a fully connected layer to map state vectors to the answers, the answer should be inclued in the original context. Thus, we can use start position and end position to represent the answer.

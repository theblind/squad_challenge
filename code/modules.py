import tensorflow as tf
from tensorflow.python.ops.rnn_cell import DropoutWrapper
from tensorflow.python.ops import variable_scope as vs
from tensorflow.python.ops import rnn_cell


class RNNEncoder(object):
    """
    General-purpose module to encode a sequence using a RNN.
    It feeds the input through a RNN and returns all the hidden states.
    """

    def __init__(self, hidden_size, keep_prob):
        """
        Inputs:
          hidden_size: int. Hidden size of the RNN
          keep_prob: Tensor containing a single scalar that is the keep probability (for dropout)
        """
        self.hidden_size = hidden_size
        self.keep_prob = keep_prob
        self.rnn_cell_fw = rnn_cell.GRUCell(self.hidden_size)
        self.rnn_cell_fw = DropoutWrapper(
            self.rnn_cell_fw, input_keep_prob=self.keep_prob)
        self.rnn_cell_bw = rnn_cell.GRUCell(self.hidden_size)
        self.rnn_cell_bw = DropoutWrapper(
            self.rnn_cell_bw, input_keep_prob=self.keep_prob)

    def build_graph(self, inputs, masks):
        """
        Inputs:
          inputs: Tensor shape (batch_size, seq_len, input_size)
          masks: Tensor shape (batch_size, seq_len).

        Returns:
          out: Tensor shape (batch_size, seq_len, hidden_size*2).
        """
        with vs.variable_scope("RNNEncoder"):
            input_lens = tf.reduce_sum(
                masks, reduction_indices=1)  # shape (batch_size)

            # Note: fw_out and bw_out are the hidden states for every timestep.
            # Each is shape (batch_size, seq_len, hidden_size).
            (fw_out, bw_out), _ = tf.nn.bidirectional_dynamic_rnn(
                self.rnn_cell_fw, self.rnn_cell_bw, inputs, input_lens,
                dtype=tf.float32, swap_memory=True)

            # Concatenate the forward and backward hidden states
            out = tf.concat([fw_out, bw_out], 2)

            # Apply dropout
            out = tf.nn.dropout(out, self.keep_prob)

            return out


class BasicAttn(object):

    def __init__(self, keep_prob, key_vec_size, value_vec_size):
        """
        Inputs:
          keep_prob: tensor containing a single scalar that is the keep probability (for dropout)
          key_vec_size: size of the key vectors. int
          value_vec_size: size of the value vectors. int
        """
        self.keep_prob = keep_prob
        self.key_vec_size = key_vec_size
        self.value_vec_size = value_vec_size

    def build_graph(self, values, values_mask, keys):
        """
        Keys attend to values.
        For each key, return an attention distribution and an attention output vector.
        """
        with vs.variable_scope("BasicAttn"):

            # Calculate attention distribution
            # (batch_size, value_vec_size, num_values)
            values_t = tf.transpose(values, perm=[0, 2, 1])
            # shape (batch_size, num_keys, num_values)
            attn_logits = tf.matmul(keys, values_t)
            # shape (batch_size, 1, num_values)
            attn_logits_mask = tf.expand_dims(values_mask, 1)
            # shape (batch_size, num_keys, num_values). take softmax over values
            _, attn_dist = masked_softmax(attn_logits, attn_logits_mask, 2)

            # Use attention distribution to take weighted sum of values
            # shape (batch_size, num_keys, value_vec_size)
            output = tf.matmul(attn_dist, values)

            # Apply dropout
            output = tf.nn.dropout(output, self.keep_prob)

            return attn_dist, output


class BidirectionAttention(BasicAttn):
    def __init__(self, keep_prob, key_vec_size, value_vec_size):
        """
        Inputs:
          keep_prob: tensor containing a single scalar that is the keep probability (for dropout)
          key_vec_size: size of the key vectors. int
          value_vec_size: size of the value vectors. int
        """
        self.keep_prob = keep_prob
        self.key_vec_size = key_vec_size
        self.value_vec_size = value_vec_size

    def build_graph(self, values, values_mask, keys, keys_mask):
        """
        Keys attend to values.
        For each key, return an attention distribution and an attention output vector.
        """
        with vs.variable_scope("BidirectionalAttention"):
            num_keys = keys.get_shape().as_list()[1]
            num_values = values.get_shape().as_list()[1]

            # Reshape keys and values
            keys_rows = tf.tile(
                input=tf.reshape(
                    keys, shape=[-1, num_keys, 1, self.value_vec_size]),
                multiples=[1, 1, num_values, 1])
            values_rows = tf.tile(
                input=tf.reshape(
                    values, shape=[-1, 1, num_values, self.value_vec_size]),
                multiples=[1, num_keys, 1, 1]
            )
            args = tf.reshape(
                tf.concat([keys_rows, values_rows, keys_rows*values_rows], 3),
                shape=[-1, 3*self.value_vec_size])

            # Calculate similarity matrix
            W = tf.get_variable("W", shape=[3*self.value_vec_size, 1])
            b = tf.get_variable("b", shape=[1])
            similarity_matrix = tf.matmul(args, W) + b
            # shape (batch_size, num_keys, num_values)
            similarity_matrix = tf.reshape(similarity_matrix,
                                           shape=[-1, num_keys, num_values])

            # Calculate keys_to_values
            # Use attention distribution to take weighted sum of values
            _, keys_to_values = masked_softmax(
                similarity_matrix, tf.expand_dims(values_mask, 1), 2)
            # shape (batch_size, num_keys, value_vec_size)
            keys_to_values = tf.matmul(keys_to_values, values)

            # Calculate values_to_keys
            # Use attention distribution to take weighted sum of keys
            values_to_keys = tf.reduce_max(
                similarity_matrix, axis=2, keep_dims=True)
            _, values_to_keys = masked_softmax(
                values_to_keys, tf.expand_dims(keys_mask, 1), 2)
            # shape (batch_size, num_values, value_vec_size)
            values_to_keys = tf.matmul(values_to_keys, keys)

            # Apply dropout
            keys_to_values = tf.nn.dropout(keys_to_values, self.keep_prob)
            values_to_keys = tf.nn.dropout(values_to_keys, self.keep_prob)

            return keys_to_values, values_to_keys


def masked_softmax(logits, mask, dim):
    """
    Takes masked softmax over given dimension of logits.
    """
    exp_mask = (1 - tf.cast(mask, 'float')) * \
        (-1e30)  # -large where there's padding, 0 elsewhere
    # where there's padding, set logits to -large
    masked_logits = tf.add(logits, exp_mask)
    prob_dist = tf.nn.softmax(masked_logits, dim)
    return masked_logits, prob_dist


class SimpleSoftmaxLayer(object):
    """
    Module to take set of hidden states, and return probability distribution over those states.
    """

    def __init__(self):
        pass

    def build_graph(self, inputs, masks):
        """
        Applies one linear downprojection layer, then softmax.
        """
        with vs.variable_scope("SimpleSoftmaxLayer"):

            # Linear downprojection layer
            logits = tf.contrib.layers.fully_connected(
                inputs, num_outputs=1, activation_fn=None)  # shape (batch_size, seq_len, 1)
            # shape (batch_size, seq_len)
            logits = tf.squeeze(logits, axis=[2])

            # Take softmax over sequence
            masked_logits, prob_dist = masked_softmax(logits, masks, 1)

            return masked_logits, prob_dist

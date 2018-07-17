import tensorflow as tf
import numpy as np
from math import ceil
import sys
import os
from attention_cell import AttentionBasedGRUCell


class RNN(object):
    """ RNN model """
    def __init__(self, config, word_vectors=[]):
        self.dim_proj = config['dim_proj']
        self.layers = config['layers']
        self.l2_weight = config["l2_norm_w"]
        self.batch_size = tf.placeholder(tf.int32, name="batch_size")
        self.n_words = config['n_words']
        self.learning_rate = config['learning_rate']
        self.num_classes = config['classes_num']
        self.word_vectors = word_vectors
        self.global_step = tf.Variable(0, name="global_step", trainable=False)
        self.input_keep_prob = tf.placeholder(
            tf.float32, name="keep_prob_inp")
        self.output_keep_prob = tf.placeholder(
            tf.float32, name="keep_prob_out")
        self.sentence_len = config['sentence_len']
        self.max_gradient_norm = config["clip_threshold"]
        self.x = tf.placeholder(tf.int32, [None, self.sentence_len], name="x")
        self.y = tf.placeholder(tf.float32, [None, self.num_classes], name="y")

        self.dropout_prob = tf.placeholder(tf.float32, name="dropout_prob")

        # values vital when using minibatches on dev set
        # really ugly workaround
        self.metrics_weight = tf.placeholder(tf.float32, name="metrics_weight")
        self.fixed_acc_value = tf.placeholder(tf.float32, name="f_acc_value")
        self.fixed_loss_value = tf.placeholder(tf.float32, name="f_loss_value")

        self.make_graph(config)
        self.summarize(config)

    def make_graph(self, config):
        """ Build RNN graph """

        with tf.name_scope("word_embeddings"):
            #     self.word_embeddings = []
            #     all_embeddings = []
            #     # counter = 0
            #     for index_ in range(self.word_vectors.shape[0]):
            #         if config['train_embeddings'][index_] is None:
            #             continue
            #         extracted_emb = tf.get_variable(
            #             "W0_" + str(index_), shape=[self.n_words, self.edim],
            #             trainable=config['train_embeddings'][index_],
            #             initializer=tf.constant_initializer(
            #                 np.array(self.word_vectors[index_]))
            #         )
            #         self.word_embeddings.append(extracted_emb)
            #         temp = tf.nn.embedding_lookup(
            #             extracted_emb, self.x)
            #         all_embeddings.append(temp)
            # self.embedded_chars = tf.stack(all_embeddings, axis=3)

            # print ("emb_char shape: {}".format(self.embedded_chars.shape))
            # self.w_embeddings = tf.get_variable(
            #     "W_embeddings",
            #     [self.n_words, self.dim_proj],
            #     initializer=tf.random_uniform_initializer(-1.0, 1.0)

            # )
            # self.w_embeddings = tf.Variable(
            #     tf.truncated_normal([self.n_words, self.dim_proj],
            #                         stddev=0.01),
            #     name="W_embeddings")
            index_ = 0 # curently using only a single type of word embeddings
            self.w_embeddings = tf.get_variable(
                "W0_" + str(index_),
                shape=[self.n_words, self.dim_proj],
                trainable=config['train_embeddings'][index_],
                initializer=tf.constant_initializer(
                    np.array(self.word_vectors[index_]))
            )

            embedded_tokens = tf.nn.embedding_lookup(
                self.w_embeddings, self.x)
            print("emb_tokens {} rnn_input  ".format(embedded_tokens.shape))
            # embedded_tokens_drop = tf.nn.dropout(embedded_tokens, self.dropout_keep_prob_embedding)
        # split sentences in word steps of size batch_size
        rnn_input = [embedded_tokens[:, i, :] for i in range(
            self.sentence_len)]

        with tf.name_scope("calc_sequences_length"):
            '''
            calculate actual lenght of each sentence -- known bug
            if a sentence ends with unknown tokens they are not considered
            in size, if they are at start or in between they are
            considered though
            '''
            # doesn't work due to zero padding and <UNK> being both zero
            # self.seq_lengths = tf.reduce_sum(tf.sign(self.x), 1)
            mask = tf.sign(self.x)
            range_ = tf.range(
                start=1, limit=self.sentence_len + 1, dtype=tf.int32)
            mask = tf.multiply(mask, range_, name="mask")
            self.seq_lengths = tf.reduce_max(mask, axis=1)

        with tf.name_scope("rnn_cell"):
            if config['GRU']:  # use GRU cell
                self.rnn_cell = tf.contrib.rnn.DropoutWrapper(
                    tf.contrib.rnn.GRUCell(num_units=self.dim_proj),
                    input_keep_prob=self.input_keep_prob,
                    output_keep_prob=self.output_keep_prob
                )
                if config['attention']:
                    self.rnn_cell = tf.contrib.rnn.AttentionCellWrapper(
                        cell=self.rnn_cell, attn_length=40, state_is_tuple=True
                    )

                # rnn_cell = tf.contrib.rnn.GRUCell(num_units=self.dim_proj)
            else:  # use lstm cell instead
                self.rnn_cell = tf.contrib.rnn.DropoutWrapper(
                    tf.contrib.rnn.LSTMCell(num_units=self.dim_proj),
                    input_keep_prob=self.input_keep_prob,
                    output_keep_prob=self.output_keep_prob
                )
                if config['attention']:
                    self.rnn_cell = tf.contrib.rnn.AttentionCellWrapper(
                        cell=self.rnn_cell, attn_length=40, state_is_tuple=True
                    )


            # create sequential rnn from single cells
            rnn_cell_seq = tf.contrib.rnn.MultiRNNCell(
                [self.rnn_cell] * self.layers, state_is_tuple=True)

            initial_state = rnn_cell_seq.zero_state(
                self.batch_size, tf.float32)
            # Create a recurrent neural network

            if config['bidirectional']:
                output, state_fw, state_bw = tf.contrib.rnn.static_bidirectional_rnn(
                    inputs=rnn_input,
                    cell_fw=rnn_cell_seq,
                    cell_bw=rnn_cell_seq,
                    initial_state_fw=initial_state,
                    initial_state_bw=initial_state,
                    sequence_length=self.seq_lengths
                )
                if config["GRU"]:
                    self.output = tf.concat([state_fw[-1], state_bw[-1]], 1)
                    # self.output = state_fw[-1] + state_bw[-1]
                    # self.output = output[-1]
                else:  # LSTM
                    self.output = tf.concat(
                        [state_fw[0][-1], state_bw[0][-1]], 1)

                self.times = 2

            else:
                # self.lengths = tf.reduce_sum(
                #     tf.reduce_max(tf.sign(self.x), 2), 1)
                # self.lengths = tf.reduce_sum(tf.sign(self.x), 1)
                output, state = tf.contrib.rnn.static_rnn(
                    rnn_cell_seq, rnn_input,
                    initial_state=initial_state,
                    sequence_length=self.seq_lengths
                )
                if config['GRU']:
                    self.output = state[-1]
                else:
                    self.output = state[0][-1]
                # output, state = tf.nn.dynamic_rnn(
                #     cell=rnn_cell_seq,
                #     inputs=rnn_input,
                #     initial_state=initial_state,
                #     # sequence_length=self.seq_lengths
                # )

                self.times = 1
            if config["pool_all_output"]:
                # Do average pooling over all outputs
                with tf.name_scope("pool_all_output"):
                    self.poolings = []
                    for i in range(self.sentence_len):
                        pool_shape = [self.batch_size, 1, -1, 1]
                        pool_input = tf.reshape(
                            self.output[i], pool_shape
                        )
                        pool = tf.nn.avg_pool(
                            pool_input, strides=[1, 1, 1, 1],
                            ksize=[1, 1, self.dim_proj, 1],
                            padding='VALID', name="avg_pool_ouput"
                        )
                        pool = tf.reshape(
                            pool, [-1])
                        self.poolings.append(pool)
                    self.stacked_outputs = tf.stack(self.poolings)
                    self.state_ = tf.matrix_transpose(
                        self.stacked_outputs, name="stacked_avg_outputs")
                    print ("state_ shape: {}".format(self.state_.shape))
            else:
                # self.state_ = self.output[-1]
                self.state_ = self.output


                # self.stacked_outputs = tf.reshape(
                #     self.stacked_outputs, out_shape)

                # self.output_pool = 
                # self.state_ = output[-1]

                # self.state = state[-1][0] + state[-1][1]
                # self.state_ = tf.concat([state[-1][0], state[-1][1]], 1)
        if config["pooling"]:
            '''
            avg pooling over [output/state]
            '''
            with tf.name_scope("avg_pooling"):
                self.h_pool = tf.reshape(
                    self.state_, [self.batch_size, -1, 1, 1])
                self.pool = tf.nn.avg_pool(
                    self.h_pool, strides=[1, 1, 1, 1],
                    # ksize=[1, self.sentence_len + 1, 1, 1],
                    # ksize=[1, self.times * self.dim_proj, 1, 1],
                    ksize=[1, self.state_.shape[1], 1, 1],
                    padding='VALID', name="pool"
                )
            with tf.name_scope("softmax"):
                self.flat_pool = tf.reshape(self.pool, [-1, 1])
                shape = [1, self.num_classes]
                W = tf.Variable(
                    tf.truncated_normal(shape, stddev=0.01), name='W'
                )
                b = tf.Variable(tf.constant(
                    0.1, shape=[self.num_classes]),
                    name="b"
                )
                self.scores = tf.nn.xw_plus_b(self.flat_pool, W, b)
                tf.add_to_collection('l2_loss', tf.nn.l2_loss(W))

        else:
            with tf.name_scope("drop_out"):
                '''
                fc layer over [output/state]
                '''
                # use the cell memory state for information on sentence embedding
                self.l_drop = tf.nn.dropout(
                    self.state_, self.dropout_prob, name="drop_out")
                # self.l_drop = self.state_

            with tf.name_scope("fc_layer"):

                shape = [int(self.state_.shape[1]), self.num_classes]
                # hidden_layer_dim = 150
                # shape = [int(self.state_.shape[1]), hidden_layer_dim]
                # W = tf.Variable(
                #     tf.truncated_normal(shape, stddev=0.01), name="W",
                # )

                W = self.xavier_init(shape, "W")
                b = tf.Variable(tf.constant(
                    0.1, shape=[self.num_classes]),
                    trainable=True, name="b"
                )
                tf.add_to_collection('l2_loss', tf.nn.l2_loss(W))
                self.scores = tf.nn.xw_plus_b(self.l_drop, W, b)

                # add another layer
                # self.scores = tf.nn.relu(self.scores, name='RELU_1')
                # shape = [hidden_layer_dim, self.num_classes]
                # W_2 = tf.Variable(
                #     tf.truncated_normal(shape, stddev=0.01), name="W",
                # )
                # b_2 = tf.Variable(tf.constant(
                #     0.1, shape=[self.num_classes]),
                #     trainable=True, name="b"
                # )
                # self.scores = tf.nn.xw_plus_b(self.scores, W_2, b_2)

                # self.scores = tf.nn.sigmoid(self.scores, name='sigmoid')

        # self.y = tf.nn.softmax(self.scores)
        with tf.name_scope("predict"):
            self.predictions = tf.argmax(self.scores, 1)
            self.true_predictions = tf.argmax(self.y, 1)
            self.probs = tf.nn.softmax(self.scores)
        with tf.name_scope("loss"):
            self.losses = tf.nn.softmax_cross_entropy_with_logits(
                logits=self.scores, labels=self.y, name="losses")
            self.total_l2_norm = tf.add_n(tf.get_collection('l2_loss'))
            # self.total_loss = tf.reduce_sum(self.losses)
            self.mean_loss = (tf.reduce_mean(self.losses) +
                              self.l2_weight * self.total_l2_norm)
        with tf.name_scope("accuracy"):
            self.correct_predictions = tf.equal(
                self.predictions, tf.argmax(self.y, 1))
            self.accuracy = tf.reduce_mean(
                tf.cast(self.correct_predictions, "float"), name="accuracy")

        params = tf.trainable_variables()
        # if self.train_phase:
        with tf.name_scope("train"):
            optimizer = tf.train.AdamOptimizer(self.learning_rate)
        gradients = tf.gradients(self.mean_loss, params)
        clipped_gradients, norm = tf.clip_by_global_norm(
            gradients, self.max_gradient_norm)

        # with tf.name_scope("grad_norms"):
        #     grad_summ = tf.scalar_summary("grad_norms", norm)

        self.update = optimizer.apply_gradients(
            zip(clipped_gradients, params), global_step=self.global_step)
        # self.mean_loss = tf.scalar_summary("{0}_loss".format(
        #     self.str_summary_type), self.mean_loss)
        # acc_summ = tf.scalar_summary("{0}_accuracy".format(
        #     self.str_summary_type), self.accuracy)
        # self.merged = tf.merge_summary([self.mean_loss, acc_summ])
    # self.saver = tf.train.Saver(tf.globa())

    def xavier_init(self, shape_, var_name):
        '''initialize a variable using xavier initialization
        '''
        return tf.get_variable(
            var_name, shape=shape_,
            initializer=tf.contrib.layers.xavier_initializer()
        )

    def fc_layer(self, input_, num_layers, shapes, id_=0):
        """declare a fully connected network
        with num_layers <layers> each of shape <shapes>
        """
        with tf.name_scope("fully_conected_layer_" + str(id_)):
            final_output = None
            for layer in range(num_layers):
                weight_shape = shapes[layer]
                W = self.xavier_init(
                    weight_shape, "W_fc_{}_{}".format(id_, layer))
                b = tf.Variable(tf.constant(
                    0.1, shape=[weight_shape[1]]),
                    trainable=True, name="b_fc_{}_{}".format(id_, layer)
                )
                final_output = tf.nn.xw_plus_b(input_, W, b)
                if num_layers - layer - 1 > 0:
                    # if not on last layer apply non linearity
                    input_ = tf.nn.relu(final_output)
            return final_output

    def summarize(self, config):
        # out_dir = config['out_dir']
        # Summaries for loss and accuracy

        # if config['bidirectional']:
        #     weight = config
        #     loss_summary = tf.summary.scalar("loss", self.mean_loss)
        #     acc_summary = tf.summary.scalar("accuracy", self.accuracy)
        # else:
        self.mean_loss = self.metrics_weight * self.mean_loss + \
            self.fixed_loss_value
        self.accuracy = self.metrics_weight * self.accuracy + \
            self.fixed_acc_value
        loss_summary = tf.summary.scalar("loss", self.mean_loss)
        acc_summary = tf.summary.scalar("accuracy", self.accuracy)
        w_norm_summary = tf.summary.scalar("weight_norm", self.total_l2_norm)
        # Train Summaries
        self.summary_op = tf.summary.merge(
            [loss_summary, acc_summary, w_norm_summary])
        # Dev summaries
        # self.dev_summary_op = tf.summary.merge([loss_summary, acc_summary])


class RNN_Attention(object):

    """ RNN model  using attention"""
    def __init__(self, config, word_vectors=[]):
        self.dim_proj = config['dim_proj']
        self.layers = config['layers']
        self.l2_weight = config["l2_norm_w"]
        self.batch_size = tf.placeholder(tf.int32, name="batch_size")
        self.n_words = config['n_words']
        self.learning_rate = config['learning_rate']
        self.num_classes = config['classes_num']
        self.word_vectors = word_vectors
        self.global_step = tf.Variable(0, name="global_step", trainable=False)
        self.input_keep_prob = tf.placeholder(
            tf.float32, name="keep_prob_inp")
        self.output_keep_prob = tf.placeholder(
            tf.float32, name="keep_prob_out")
        self.sentence_len = config['sentence_len']
        self.max_gradient_norm = config["clip_threshold"]
        self.x = tf.placeholder(tf.int32, [None, self.sentence_len], name="x")
        self.y = tf.placeholder(tf.float32, [None, self.num_classes], name="y")

        self.dropout_prob = tf.placeholder(tf.float32, name="dropout_prob")

        # values vital when using minibatches on dev set
        # really ugly workaround
        self.metrics_weight = tf.placeholder(tf.float32, name="metrics_weight")
        self.fixed_acc_value = tf.placeholder(tf.float32, name="f_acc_value")
        self.fixed_loss_value = tf.placeholder(tf.float32, name="f_loss_value")
        self.make_graph(config)
        self.train()
        self.summarize(config)

    def make_graph(self, config):
        """ declare RNN graph """

        with tf.name_scope("word_embeddings"):
            """
            initialize embeddings currently able to use only one type of
            embeddings
            """
            index_ = 0
            self.w_embeddings = tf.get_variable(
                "W0_" + str(index_),
                shape=[self.n_words, self.dim_proj],
                trainable=config['train_embeddings'][index_],
                initializer=tf.constant_initializer(
                    np.array(self.word_vectors[index_]))
            )
            embedded_tokens = tf.nn.embedding_lookup(
                self.w_embeddings, self.x)
            print("emb_tokens {} rnn_input  ".format(embedded_tokens.shape))

        # split sentences in word steps of size batch_size
        rnn_input = [embedded_tokens[:, i, :] for i in range(
            self.sentence_len)]

        with tf.name_scope("calc_sequences_length"):
            '''
            calculate actual lenght of each sentence -- known bug
            if a sentence ends with unknown tokens they are not considered
            in size, if they are at start or in between they are
            considered though
            '''
            # this doesn't work due to zero padding and <UNK> being both zero
            # self.seq_lengths = tf.reduce_sum(tf.sign(self.x), 1)
            mask = tf.sign(self.x)
            range_ = tf.range(
                start=1, limit=self.sentence_len + 1, dtype=tf.int32)
            mask = tf.multiply(mask, range_, name="mask")
            self.seq_lengths = tf.reduce_max(mask, axis=1)

        with tf.name_scope("rnn_cell"):
            if config['GRU']:  # use GRU cell
                self.rnn_cell = tf.contrib.rnn.DropoutWrapper(
                    tf.contrib.rnn.GRUCell(num_units=self.dim_proj),
                    input_keep_prob=self.input_keep_prob,
                    output_keep_prob=self.output_keep_prob
                )
            else:
                # TODO LSTM fix
                self.rnn_cell = tf.contrib.rnn.DropoutWrapper(
                    tf.contrib.rnn.LSTMCell(num_units=self.dim_proj),
                    input_keep_prob=self.input_keep_prob,
                    output_keep_prob=self.output_keep_prob,
                )

        # create sequential rnn from single cells
        rnn_cell_seq = tf.contrib.rnn.MultiRNNCell(
            [self.rnn_cell] * self.layers, state_is_tuple=True)

        initial_state = rnn_cell_seq.zero_state(
            self.batch_size, tf.float32)

        if config['bidirectional']:
            self.dimensionality_mult = 2
            output, state_fw, state_bw = tf.contrib.rnn.static_bidirectional_rnn(
                inputs=rnn_input,
                cell_fw=rnn_cell_seq,
                cell_bw=rnn_cell_seq,
                initial_state_fw=initial_state,
                initial_state_bw=initial_state,
                sequence_length=self.seq_lengths
            )
            self.output = output

        else:
            self.dimensionality_mult = 1
            output, state = tf.contrib.rnn.static_rnn(
                rnn_cell_seq, rnn_input,
                initial_state=initial_state,
                sequence_length=self.seq_lengths
            )
            self.out_state = state
            self.output = output

        # self.attention_old(config)
        self.attention(config)

    def attention(self, config):
        with tf.name_scope("attention_fc_layer"):
            # reshape out put to be [batches, seq_length, word_dimensionality]
            self.output = np.asarray(self.output)
            self.output = tf.stack(list(self.output))

            # change sequence of dimensions
            self.attention_input = tf.transpose(
                self.output, perm=[1, 0, 2])

            w_1_dim = 512
            hidden_z_shape = [self.dim_proj * self.dimensionality_mult, w_1_dim]
            g_tensor = tf.Variable(tf.truncated_normal(
                [1, self.dim_proj]), name="g_scores")
            i = tf.constant(0)


            W_1 = tf.get_variable(
                "att_weight_1", shape=hidden_z_shape,
                initializer=tf.contrib.layers.xavier_initializer()
            )
            b_1 = tf.Variable(tf.constant(
                0.1, shape=[w_1_dim]), name="att_bias_1")
            # W_2 = tf.get_variable(
            #     "att_weight_2", shape=[w_1_dim, 1],
            #     initializer=tf.contrib.layers.xavier_initializer()
            # )
            # b_2 = tf.Variable(tf.constant(
            #     0.1, shape=[1]), name="att_bias_2")
            w_2_dim = 512
            W_2 = tf.get_variable(
                "att_weight_2", shape=[w_1_dim, w_2_dim],
                initializer=tf.contrib.layers.xavier_initializer()
            )
            b_2 = tf.Variable(tf.constant(
                0.1, shape=[w_2_dim]), name="att_bias_2")

            W_3 = tf.get_variable(
                "att_weight_3", shape=[w_2_dim, 1],
                initializer=tf.contrib.layers.xavier_initializer()
            )
            b_3 = tf.Variable(tf.constant(
                0.1, shape=[1]), name="att_bias_3")




            tf.add_to_collection('l2_loss', tf.nn.l2_loss(W_1))
            tf.add_to_collection('l2_loss', tf.nn.l2_loss(W_2))

            with tf.name_scope("attention_calculation"):
                def condition(i, g_tensor):
                    return tf.less(i, self.batch_size)

                def body(i, g_tensor):
                    up_to = self.seq_lengths[i]
                    # if sentence was full with <unk> 
                    # (i.e seq_lengths[i] == 0) just take a vector of zeros
                    # as fact representation
                    up_to = tf.cond(
                        tf.equal(up_to, 0), lambda: tf.constant(1),
                        lambda: up_to
                    )

                    fact = tf.slice(
                        self.attention_input, [i, 0, 0], [1, up_to, -1])

                    fact = tf.reshape(fact, [up_to, -1])

                    # # calculate attention values
                    inter = tf.nn.tanh(
                        tf.nn.xw_plus_b(fact, W_1, b_1)
                    )

                    # # calculate attention values
                    inter_2 = tf.nn.tanh(
                        tf.nn.xw_plus_b(inter, W_2, b_2)
                    )
                    unorm_att = tf.nn.xw_plus_b(inter_2, W_3, b_3)


                    # unorm_att = tf.nn.xw_plus_b(inter, W_2, b_2)

                    # softmax values g_i
                    g_i = tf.nn.softmax(tf.transpose(unorm_att))

                    # zero pad attentions to fit in tensor
                    paddings = [[0, 0],
                                [0, self.sentence_len - up_to]]
                    padded_g_i = tf.pad(g_i, paddings, "CONSTANT")
                    padded_g_i = tf.reshape(padded_g_i, [1, -1])
                    g_tensor = tf.cond(
                        tf.equal(i, 0), lambda: padded_g_i, lambda: tf.concat(
                            [g_tensor, padded_g_i], axis=0)
                    )

                    i = tf.add(i, 1)
                    return [i, g_tensor]

                _, g_tensor = tf.while_loop(
                    condition, body, [i, g_tensor],
                    shape_invariants=[i.get_shape(),
                                      tf.TensorShape([None, None])]
                )
                g_tensor = tf.reshape(g_tensor, [-1, self.sentence_len])
                self.attention_scores = g_tensor

            if config['attention_GRU']:
                with tf.name_scope("attention_GRU"):
                    self.attention_scores_exp = tf.expand_dims(
                        self.attention_scores, axis=-1)
                    inputs = tf.concat(
                        [self.attention_input, self.attention_scores_exp], 2)
                    attention_cell = tf.contrib.rnn.DropoutWrapper(
                        AttentionBasedGRUCell(
                            num_units=self.dim_proj * self.dimensionality_mult),
                        input_keep_prob=self.input_keep_prob,
                        output_keep_prob=self.output_keep_prob
                    )
                    rnn_cell_seq = tf.contrib.rnn.MultiRNNCell(
                        [attention_cell] * 1, state_is_tuple=True)
                    initial_state = rnn_cell_seq.zero_state(
                        self.batch_size, tf.float32)
                    _, c_t = tf.nn.dynamic_rnn(
                        inputs=inputs, cell=rnn_cell_seq,
                        sequence_length=self.seq_lengths,
                        initial_state=initial_state)
                    self.state_ = c_t[-1]
            else:  # calculate representation as a weighted sum
                with tf.name_scope("attention_weighted_sum"):
                    attention_expanded = tf.expand_dims(
                        self.attention_scores, -1)
                    self.state_ = tf.reduce_sum(
                        tf.multiply(
                            self.attention_input, attention_expanded), 1)

                    # print (self.state_)
                    # sys.exit()

        with tf.name_scope("drop_out"):
            self.l_drop = tf.nn.dropout(
                self.state_, self.dropout_prob, name="drop_out")

        with tf.name_scope("fc_layer"):
            shape = [self.dim_proj * self.dimensionality_mult, self.num_classes]
            W = tf.Variable(
                tf.truncated_normal(shape, stddev=0.01),
                name="W_fc_layer")
            b = tf.Variable(tf.constant(
                0.1, shape=[self.num_classes]),
                name="b"
            )
            tf.add_to_collection('l2_loss', tf.nn.l2_loss(W))
            self.scores = tf.nn.xw_plus_b(self.l_drop, W, b)

    def attention_old(self, config):
        ''' old crappy attnetion caclulation '''
        with tf.name_scope("attention_fc_layer"):
            # reshape out put to be [batches, seq_length, word_dimensionality]
            self.output = np.asarray(self.output)
            self.output = tf.stack(list(self.output))

            # change sequence of dimensions
            self.attention_input = tf.transpose(
                self.output, perm=[1, 0, 2])

            shape = [self.dim_proj * self.dimensionality_mult, 1]
            W = tf.Variable(
                tf.truncated_normal(shape, stddev=0.01),
                name="W_attent_fc"
            )
            b = tf.Variable(
                tf.constant(0.1, shape=[self.sentence_len]),
                name="b"
            )
            tf.add_to_collection('l2_loss', tf.nn.l2_loss(W))
            # reshape 3d tensor to be mjltiplied by the weights
            temp_shape_in = [
                self.batch_size * self.sentence_len, self.dim_proj * self.dimensionality_mult]
            # shape_out = [self.batch_size, self.sentence_len, 1]
            shape_out = [self.batch_size, self.sentence_len]
            self.unormalized_att_scores = tf.reshape(
                tf.matmul(tf.reshape(
                    self.attention_input, temp_shape_in), W), shape_out)

            # force not to put weights at all after each sentence len is done
            # filter_ = tf.ones_like(self.unormalized_att_scores, name='y') *\
            #     -10**6
            # case_ = tf.logical_or(
            #     self.unormalized_att_scores > 0,
            #     self.unormalized_att_scores < 0)
            # self.unormalized_att_scores = tf.where(
            #     case_, self.unormalized_att_scores, filter_)

            # relu
            # self.unormalized_att_scores = tf.nn.relu(
            #     tf.nn.bias_add(self.unormalized_att_scores, b), name="relu")
            # or tanh
            self.unormalized_att_scores = tf.nn.tanh(
                tf.nn.bias_add(self.unormalized_att_scores, b), name="tanh")
            # or sigmoid
            # self.unormalized_att_scores = tf.nn.sigmoid(
            #     tf.nn.bias_add(self.unormalized_att_scores, b), name="sigmoid")

            # put a second fc layer -- bad
            # shape = [self.sentence_len, self.sentence_len]
            # W2 = tf.Variable(
            #     tf.truncated_normal(shape, stddev=0.01),
            #     name="W_attent_fc_2")
            # b = tf.Variable(
            #     tf.constant(0.1, shape=[self.sentence_len]),
            #     name="b"
            # )
            # self.unormalized_att_scores = tf.nn.xw_plus_b(
            #     self.unormalized_att_scores, W2, b)
            # self.unormalized_att_scores = tf.nn.relu(
            #     self.unormalized_att_scores, name="relu")

            # punish values after end of sentence/doesn't work nice
            # self.unormalized_att_scores = tf.where(
            #     case_, self.unormalized_att_scores, filter_)

            # caclulate attention using a for loop over the batch in order
            # not to take into account zero padding
            # print ("unormalized attentio scores +++ ", self.unormalized_att_scores.shape)

            # initialize tensors, (size doesn't matter)
            a_list = tf.Variable(
                tf.truncated_normal(
                    [1, self.dim_proj]), name="representations")
            list_scores = tf.Variable(
                tf.truncated_normal(
                    [1, self.dim_proj]), name="attention_scores")
            i = tf.constant(0)

            def condition(i, a_list, list_scores):
                # return tf.less(i, 20)
                return tf.less(i, self.batch_size)

            def body(i, a_list, list_scores):
                up_to = self.seq_lengths[i]

                temp_slice = tf.slice(
                    self.unormalized_att_scores, [i, 0], [1, up_to])
                softmax_ = tf.nn.softmax(temp_slice)

                attention_scores_exp = tf.expand_dims(softmax_, 2)
                temp_slice_input = tf.slice(
                    self.attention_input, [i, 0, 0], [1, up_to, -1])
                repr_ = tf.multiply(temp_slice_input, attention_scores_exp)
                sent_repr_ = tf.reduce_sum(repr_, 1)

                a_list = tf.cond(
                    tf.equal(i, 0), lambda: sent_repr_, lambda: tf.concat(
                        [a_list, sent_repr_], axis=0)
                )
                # zero pad attentions to fit in tensor
                paddings = [[0, 0], [0, self.sentence_len - self.seq_lengths[i]]]

                padded_softmax = tf.pad(softmax_, paddings, "CONSTANT")
                padded_softmax = tf.reshape(padded_softmax, [1, -1])
                list_scores = tf.cond(
                    tf.equal(i, 0), lambda: padded_softmax, lambda: tf.concat(
                        [list_scores, padded_softmax], axis=0)
                )

                i = tf.add(i, 1)
                return [i, a_list, list_scores]

            _, self.a_list, self.attention_scores = tf.while_loop(
                condition, body, [i, a_list, list_scores],
                shape_invariants=[i.get_shape(),
                                  tf.TensorShape([None, None]),
                                  tf.TensorShape([None, None])]
            )
            # self.attention_scores = tf.Variable(self.attention_scores, validate_shape=False, name="attention_scores_in_variable")
            tf.add_to_collection(
                    'l1_loss', tf.norm(self.attention_scores, axis=1, ord=2))
            # attentions_to_tensor = tf.Variable(self.attention_scores, name="tensor_attentions")
            # tf.add_to_collection('the_attention_scores', self.attention_scores)
            if config['attention_GRU']:
                with tf.name_scope("attention_GRU"):
                    """ use attention GRU in similar fashion to a DMN
                    """
                    self.attention_scores_exp = tf.expand_dims(
                        self.attention_scores, axis=-1)
                    inputs = tf.concat(
                        [self.attention_input, self.attention_scores_exp], 2)
                    # print (" att GRU inputs {} shape {}".format(inputs, inputs.shape))
                    attention_cell = tf.contrib.rnn.DropoutWrapper(
                        AttentionBasedGRUCell(
                            num_units=self.dim_proj * self.dimensionality_mult),
                        input_keep_prob=self.input_keep_prob,
                        output_keep_prob=self.output_keep_prob
                    )
                    rnn_cell_seq = tf.contrib.rnn.MultiRNNCell(
                        [attention_cell] * 1, state_is_tuple=True)
                    initial_state = rnn_cell_seq.zero_state(
                        self.batch_size, tf.float32)
                    _, c_t = tf.nn.dynamic_rnn(
                        inputs=inputs, cell=rnn_cell_seq,
                        sequence_length=self.seq_lengths,
                        initial_state=initial_state)
                    self.state_ = c_t[-1]

                    # print ("att GRU state_ ", self.state_)

            else:
                representations_shape = [-1, self.dim_proj * self.dimensionality_mult]
                self.a_list = tf.reshape(self.a_list, representations_shape)

                self.sentence_repr = tf.reshape(self.a_list, representations_shape)
                # TODO wtite it better and more modular
                self.state_ = self.sentence_repr

        # attention using whole tensor in  caclulation, 
        # OPPOSITE to each and every sentence length, 
        # as a result, attention mass is distributed
        # in all entries untill max_sentence_length
        # with tf.name_scope("attention_softmax"):
        #     self.attention_scores = tf.nn.softmax(self.unormalized_att_scores)
        #     print ("attentio scores +++ ", self.attention_scores.shape)
        #     print ("att input +++", self.attention_input.shape)
        # with tf.name_scope("sentence_representation"):
        #     self.attention_scores_exp = tf.expand_dims(
        #         self.attention_scores, 2)
        #     print ("attention_scores_exp ++ ", self.attention_scores_exp.shape)

        #     self.sentence_repr = tf.multiply(
        #         self.attention_input, self.attention_scores_exp)
        #     print ("sentence repr ++ ", self.sentence_repr.shape)

        #     self.sentence_repr = tf.reduce_sum(self.sentence_repr, 1)
        #     print ("sentence repr reduced ++ ", self.sentence_repr.shape)
        #     self.state_ = self.sentence_repr

        with tf.name_scope("drop_out"):
            self.l_drop = tf.nn.dropout(
                self.state_, self.dropout_prob, name="drop_out")

        with tf.name_scope("fc_layer"):
            shape = [self.dim_proj * self.dimensionality_mult, self.num_classes]
            W = tf.Variable(
                tf.truncated_normal(shape, stddev=0.01),
                name="W_fc_layer")
            b = tf.Variable(tf.constant(
                0.1, shape=[self.num_classes]),
                name="b"
            )
            tf.add_to_collection('l2_loss', tf.nn.l2_loss(W))
            self.scores = tf.nn.xw_plus_b(self.l_drop, W, b)

    def train(self):
        """ calculate accuracies, train and predict """
        with tf.name_scope("predict"):
            self.predictions = tf.argmax(self.scores, 1)
            self.true_predictions = tf.argmax(self.y, 1)
            self.probs = tf.nn.softmax(self.scores)
        with tf.name_scope("loss"):
            self.losses = tf.nn.softmax_cross_entropy_with_logits(
                logits=self.scores, labels=self.y, name="losses")
            self.total_l2_norm = tf.add_n(tf.get_collection('l2_loss'))
            # self.total_l1_norm = tf.reduce_sum(tf.add_n(tf.get_collection('l1_loss')))
            self.total_l1_norm = 0
            # self.total_loss = tf.reduce_sum(self.losses)
            self.mean_loss = (tf.reduce_mean(self.losses) +
                              self.l2_weight * self.total_l2_norm +
                              10 * self.total_l1_norm)
        with tf.name_scope("accuracy"):
            self.correct_predictions = tf.equal(
                self.predictions, tf.argmax(self.y, 1))
            self.accuracy = tf.reduce_mean(
                tf.cast(self.correct_predictions, "float"), name="accuracy")

        params = tf.trainable_variables()
        # params = tf.get_collection('l1_loss')
        params = params + tf.get_collection('the_attention_scores')
        # params = tf.get_default_graph().get_operations()
        # print (params)
        # for par in params:
        #     print (par.name)
        # sys.exit()
        with tf.name_scope("train"):
            optimizer = tf.train.AdamOptimizer(self.learning_rate)
        gradients = tf.gradients(self.mean_loss, params)
        clipped_gradients, norm = tf.clip_by_global_norm(
            gradients, self.max_gradient_norm)

        # with tf.name_scope("grad_norms"):
        #     grad_summ = tf.scalar_summary("grad_norms", norm)

        self.update = optimizer.apply_gradients(
            zip(clipped_gradients, params), global_step=self.global_step)

    def summarize(self, config):
        # out_dir = config['out_dir']
        # Summaries for loss and accuracy

        # if config['bidirectional']:
        #     weight = config
        #     loss_summary = tf.summary.scalar("loss", self.mean_loss)
        #     acc_summary = tf.summary.scalar("accuracy", self.accuracy)
        # else:
        self.mean_loss = self.metrics_weight * self.mean_loss + \
            self.fixed_loss_value
        self.accuracy = self.metrics_weight * self.accuracy + \
            self.fixed_acc_value
        loss_summary = tf.summary.scalar("loss", self.mean_loss)
        acc_summary = tf.summary.scalar("accuracy", self.accuracy)
        w_norm_summary = tf.summary.scalar("weight_norm", self.total_l2_norm)
        att_norm = tf.summary.scalar("attention_norm", self.total_l1_norm)
        # Summaries
        self.summary_op = tf.summary.merge(
            [loss_summary, acc_summary, w_norm_summary])
        # Dev summaries
        # self.dev_summary_op = tf.summary.merge([loss_summary, acc_summary])

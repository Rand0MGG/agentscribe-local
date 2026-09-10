"""CUDA session adapter for deepfilter-stream 0.1.0 (MIT).

Initialization adapted from wuxuedaifu/deepfilter-stream/model.py. Stream/state
logic stays upstream; session options avoid unsupported CUDA Conv+Sigmoid fusion.
"""
import numpy as np


def portable_graph(path):
    """Unfuse the CPU-exported Sigmoid convolution without changing weights."""
    import onnx
    model = onnx.load(path)
    nodes = []
    for node in model.graph.node:
        attrs = {a.name: onnx.helper.get_attribute_value(a) for a in node.attribute}
        if node.domain == "com.microsoft" and node.op_type == "FusedConv" and attrs.get("activation") == b"Sigmoid":
            if len(node.input) != 3 or "activation_params" in attrs:
                raise ValueError("DF3 融合卷积格式发生变化，无法安全转换。")
            attrs.pop("activation")
            middle = node.output[0] + "_linguaflow_conv"
            nodes.append(onnx.helper.make_node("Conv", list(node.input), [middle], name=node.name + "_conv", **attrs))
            nodes.append(onnx.helper.make_node("Sigmoid", [middle], list(node.output), name=node.name + "_sigmoid"))
        else:
            nodes.append(node)
    del model.graph.node[:]
    model.graph.node.extend(nodes)
    onnx.checker.check_model(model)
    return model.SerializeToString()


def cuda_model(root):
    import onnxruntime as ort
    from deepfilter_stream import DeepFilterModel

    class CudaModel(DeepFilterModel):
        def __init__(self):
            options = ort.SessionOptions()
            options.intra_op_num_threads = options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            options.log_severity_level = 3
            self.session = ort.InferenceSession(portable_graph(root / "denoiser_model.onnx"), options,
                providers=[("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC",
                    "cudnn_conv_use_max_workspace": "0", "gpu_mem_limit": str(512 * 1024 * 1024)})])
            self.input_names = [item.name for item in self.session.get_inputs()]
            self.output_names = [item.name for item in self.session.get_outputs()]
            self.frame_size = int(self.session.get_inputs()[0].shape[0])
            self.sample_rate = 48000
            with np.load(root / "initial_states.npz", allow_pickle=False) as states:
                self._init = {name: states[name].astype(np.float32) for name in self.input_names[1:]}

    return CudaModel()

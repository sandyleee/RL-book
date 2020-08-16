from __future__ import annotations
from abc import ABC
from typing import Sequence, Mapping, Tuple, TypeVar, Callable, List, Dict, \
    Generic, Optional
from copy import deepcopy
import numpy as np
from dataclasses import dataclass
from more_itertools import pairwise

X = TypeVar('X')
SMALL_NUM = 1e-6


class FunctionApprox(ABC, Generic[X]):

    def evaluate(self, x_values_seq: Sequence[X]) -> np.ndarray:
        pass

    def __call__(self, x_value: X) -> float:
        return self.evaluate([x_value]).item()

    def update(
        self,
        xy_vals_seq: Sequence[Tuple[X, float]]
    ) -> FunctionApprox[X]:
        pass


@dataclass(frozen=True)
class Tabular(FunctionApprox):

    values_map: Mapping[X, float]
    counts_map: Mapping[X, int]

    def __init__(
        self,
        values_map: Mapping[X, float],
        counts_map: Mapping[X, int] = None
    ) -> None:
        object.__setattr__(self, "values_map", values_map)
        object.__setattr__(
            self,
            "counts_map",
            {x: 0. for x in values_map} if counts_map else counts_map
        )

    def evaluate(self, x_values_seq: Sequence[X]) -> np.ndarray:
        return np.array([self.values_map[x] for x in x_values_seq])

    def update(
        self,
        xy_vals_seq: Sequence[Tuple[X, float]]
    ) -> Tabular[X]:
        values_map: Dict[X, float] = deepcopy(self.values_map)
        counts_map: Dict[X, int] = deepcopy(self.counts_map)
        for x, y in xy_vals_seq:
            count: int = counts_map[x]
            values_map[x] = (values_map[x] * count + y) / (count + 1)
            counts_map[x] = count + 1
        return Tabular(values_map, counts_map)


@dataclass(frozen=True)
class AdamGradient:
    learning_rate: float
    decay1: float
    decay2: float


@dataclass(frozen=True)
class Weights:
    adam_gradient: AdamGradient
    weights: np.ndarray
    adam_cache1: np.ndarray
    adam_cache2: np.ndarray

    def __init__(
        self,
        adam_gradient: AdamGradient,
        weights: np.ndarray,
        adam_cache1: Optional[np.ndarray] = None,
        adam_cache2: Optional[np.ndarray] = None,

    ) -> None:
        object.__setattr__(self, "adam_gradient", adam_gradient)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(
            self,
            "adam_cache1",
            np.zeros_like(weights) if adam_cache1 is None else adam_cache1
        )
        object.__setattr__(
            self,
            "adam_cache2",
            np.zeros_like(weights) if adam_cache2 is None else adam_cache2
        )

    def update(self, gradient: np.ndarray) -> Weights:
        new_adam_cache1: np.ndarray = self.adam_gradient.decay1 * \
            self.adam_cache1 + (1 - self.adam_gradient.decay1) * gradient
        new_adam_cache2: np.ndarray = self.adam_gradient.decay2 * \
            self.adam_cache2 + (1 - self.adam_gradient.decay2) * gradient ** 2
        new_weights: np.ndarray = self.weights - \
            self.adam_gradient.learning_rate * self.adam_cache1 / \
            (np.sqrt(self.adam_cache2) + SMALL_NUM) * \
            np.sqrt(1 - self.adam_gradient.decay2) / \
            (1 - self.adam_gradient.decay1)
        return Weights(
            adam_gradient=self.adam_gradient,
            weights=new_weights,
            adam_cache1=new_adam_cache1,
            adam_cache2=new_adam_cache2,
        )


@dataclass(frozen=True)
class LinearFunctionApprox(FunctionApprox):

    feature_functions: Sequence[Callable[[X], float]]
    regularization_coeff: float
    weights: Weights

    def __init__(
        self,
        feature_functions: Sequence[Callable[[X], float]],
        adam_gradient: AdamGradient,
        regularization_coeff: float = 0.,
        weights: Optional[Weights] = None
    ) -> None:
        object.__setattr__(self, "feature_functions", feature_functions)
        object.__setattr__(self, "regularization_coeff", regularization_coeff)
        object.__setattr__(
            self,
            "weights",
            Weights(
                adam_gradient,
                np.zeros(len(feature_functions) + 1)
            ) if weights is None else weights
        )

    def get_feature_values(self, x_values_seq: Sequence[X]) -> np.ndarray:
        return np.array([[1.] + [f(x) for f in self.feature_functions]
                         for x in x_values_seq])

    def evaluate(self, x_values_seq: Sequence[X]) -> np.ndarray:
        return np.dot(
            self.get_feature_values(x_values_seq),
            self.weights.weights
        )

    def regularized_loss_gradient(
        self,
        xy_vals_seq: Sequence[Tuple[X, float]]
    ) -> np.ndarray:
        x_vals, y_vals = zip(*xy_vals_seq)
        feature_vals: np.ndarray = self.get_feature_values(x_vals)
        diff: np.ndarray = np.dot(feature_vals, self.weights.weights) \
            - np.array(y_vals)
        return np.dot(feature_vals.T, diff) / len(diff) \
            + self.regularization_coeff * self.weights.weights

    def update(
        self,
        xy_vals_seq: Sequence[Tuple[X, float]]
    ) -> LinearFunctionApprox[X]:
        return LinearFunctionApprox(
            feature_functions=self.feature_functions,
            adam_gradient=self.weights.adam_gradient,
            regularization_coeff=self.regularization_coeff,
            weights=self.weights.update(
                self.regularized_loss_gradient(xy_vals_seq)
            )
        )

    def direct_solve(
        self,
        xy_vals_seq: Sequence[Tuple[X, float]]
    ) -> LinearFunctionApprox[X]:
        x_vals, y_vals = zip(*xy_vals_seq)
        feature_vals: np.ndarray = self.get_feature_values(x_vals)
        feature_vals_T: np.ndarray = feature_vals.T
        left: np.ndarray = np.dot(feature_vals_T, feature_vals) \
            + self.regularization_coeff * np.eye(len(self.weights.weights))
        right: np.ndarray = np.dot(feature_vals_T, y_vals)
        return LinearFunctionApprox(
            feature_functions=self.feature_functions,
            adam_gradient=self.weights.adam_gradient,
            regularization_coeff=self.regularization_coeff,
            weights=Weights(
                adam_gradient=self.weights.adam_gradient,
                weights=np.dot(np.linalg.inv(left), right)
            )
        )


@dataclass(frozen=True)
class DNNSpec:
    neurons: Sequence[int]
    hidden_activation: Callable[[np.ndarray], np.ndarray]
    hidden_activation_deriv: Callable[[np.ndarray], np.ndarray]
    output_activation: Callable[[np.ndarray], np.ndarray]
    output_activation_deriv: Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class DNNApprox(FunctionApprox):

    feature_functions: Sequence[Callable[[X], float]]
    dnn_spec: DNNSpec
    regularization_coeff: float
    weights: Sequence[Weights]

    def __init__(
        self,
        feature_functions: Sequence[Callable[[X], float]],
        dnn_spec: DNNSpec,
        adam_gradient: AdamGradient,
        regularization_coeff: float = 0.,
        weights: Optional[Sequence[Weights]] = None
    ) -> None:
        object.__setattr__(self, "feature_functions", feature_functions)
        object.__setattr__(self, "dnn_spec", dnn_spec)
        object.__setattr__(self, "adam_gradient", adam_gradient)
        object.__setattr__(self, "regularization_coeff", regularization_coeff)
        object.__setattr__(
            self,
            "weights",
            self.init_weights(adam_gradient) if weights is None else weights
        )

    def get_feature_values(self, x_values_seq: Sequence[X]) -> np.ndarray:
        return np.array([[1.] + [f(x) for f in self.feature_functions]
                         for x in x_values_seq])

    def init_weights(
        self,
        adam_gradient: AdamGradient
    ) -> Sequence[Weights]:
        """
        These are Xavier input parameters
        """
        augmented_layers = [len(self.feature_functions)] + \
            self.dnn_spec.neurons + [1]
        return [Weights(
            adam_gradient,
            np.random.randn(output, input + 1) / np.sqrt(input + 1)
        ) for input, output in pairwise(augmented_layers)]

    def forward_propagation(
        self,
        x_values_seq: Sequence[X]
    ) -> Sequence[np.ndarray]:
        """
        :param x_values_seq: a n-length-sequence of input points
        :return: list of length (L+2) where the first (L+1) values
                 each represent the 2-D input arrays (of size n x (|I_l| + 1),
                 for each of the (L+1) layers (L of which are hidden layers),
                 and the last value represents the output of the DNN (as a
                 2-D array of length n x 1)
        """
        inp: np.ndarray = self.get_feature_values(x_values_seq)
        outputs: List[np.ndarray] = [inp]
        for w in self.weights[:-1]:
            out: np.ndarray = self.dnn_spec.hidden_activation(
                np.dot(inp, w.weights.T)
            )
            inp: np.ndarray = np.insert(out, 0, 1., axis=1)
            outputs.append(inp)
        outputs.append(
            self.dnn_spec.output_activation(
                np.dot(inp, self.weights[-1].weights.T)
            )
        )
        return outputs

    def evaluate(self, x_values_seq: Sequence[X]) -> np.ndarray:
        return self.forward_propagation(x_values_seq)[-1][:, 0]

    def backward_propagation(
        self,
        fwd_prop: Sequence[np.ndarray],
        dObj_dOL: np.ndarray
    ) -> Sequence[np.ndarray]:
        """
        :param fwd_prop: list (of length L+2), the first (L+1) elements of
        which are n x (|I_l| + 1) 2-D arrays representing the inputs to the
        (L+1) layers, and the last element is a n x 1 2-D array
        :param dObj_dOL: 1-D array of length n representing the derivative of
        objective with respect to the output of the DNN.
        L is the number of hidden layers, n is the number of points
        :return: list (of length L+1) of |O_l| x (|I_l| + 1) 2-D array,
                 i.e., same as the type of self.weights
        """
        outputs: np.ndarray = fwd_prop[-1]
        layer_inputs: Sequence[np.ndarray] = fwd_prop[:-1]
        deriv: np.ndarray = (dObj_dOL.reshape(-1, 1) *
                             self.dnn_spec.output_activation_deriv(outputs)).T
        back_prop: List[np.ndarray] = []
        # layer l deriv represents dObj/dS_l where S_l = I_l . weights_l
        # (S_l is the result of applying layer l without the activation func)
        # deriv_l is a 2-D array of dimension |I_{l+1}| x n = |O_l| x n
        # The recursive formulation of deriv is as follows:
        # deriv_{l-1} = (weights_l^T inner deriv_l) haddamard g'(S_{l-1}),
        # which is # ((|I_l| + 1) x |O_l| inner |O_l| x n) haddamard
        # (|I_l| + 1) x n, which is ((|I_l| + 1) x n = (|O_{l-1}| + 1) x n
        # (first row  of the result is removed after this calculation to yield
        # a 2-D array of dimension |O_{l-1}| x n).
        # Note: g'(S_{l-1}) is expressed as hidden layer activation derivative
        # as a function of O_{l-1} (=I_l).
        for i in reversed(range(len(self.weights))):
            # layer l gradient is deriv_l inner layer_inputs_l, which is
            # |O_l| x n inner n x (|I_l| + 1) = |O_l| x (|I_l| + 1)
            back_prop.append(np.dot(deriv, layer_inputs[i]))
            # the next line implements the recursive formulation of deriv
            deriv = (np.dot(self.weights[i].weights.T, deriv) *
                     self.dnn_spec.hidden_activation_deriv(
                         layer_inputs[i].T
                     ))[1:]
        return back_prop[::-1]

    def regularized_loss_gradient(
        self,
        xy_values_seq: Sequence[X]
    ) -> Sequence[np.ndarray]:
        """
        :param x_vals_seq: list of n data points (x points)
        :param supervisory_seq: list of n supervisory points
        :return: list (of length L+1) of |O_l| x (|I_l| + 1) 2-D array,
                 i.e., same as the type of self.weights
        This function computes the gradient (with respect to w) of
        Loss(w) = \sum_i (f(x_i; w) - y_i)^2 where f is the DNN func
        """
        x_vals, y_vals = zip(*xy_vals_seq)
        fwd_prop: Sequence[np.ndarray] = self.forward_propagation(x_vals)
        errors: np.ndarray = fwd_prop[-1][:, 0] - np.array(y_vals)
        return [x / len(errors) + self.regularization_coeff *
                self.weights[i].weights for i, x in
                enumerate(self.backward_propagation(fwd_prop, errors))]

    def update(
        self,
        xy_values_seq: Sequence[Tuple[X, float]]
    ) -> DNNApprox[X]:
        return DNNApprox(
            feature_functions=self.feature_functions,
            dnn_spec=self.dnn_spec,
            adam_gradient=self.weights[0].adam_gradient,
            regularization_coeff=self.regularization_coeff,
            weights=[w.update(g) for w, g in zip(
                self.weights,
                self.regularized_loss_gradient(xy_vals_seq)
            )]
        )


if __name__ == '__main__':

    from scipy.stats import norm
    from pprint import pprint

    alpha = 2.0
    beta_1 = 10.0
    beta_2 = 4.0
    beta_3 = -6.0
    beta = (beta_1, beta_2, beta_3)

    x_pts = np.arange(-10.0, 10.0, 0.5)
    y_pts = np.arange(-10.0, 10.0, 0.5)
    z_pts = np.arange(-10.0, 10.0, 0.5)
    pts: Sequence[Tuple[float, float, float]] = \
        [(x, y, z) for x in x_pts for y in y_pts for z in z_pts]

    def superv_func(pt):
        return alpha + np.dot(beta, pt)

    n = norm(loc=0., scale=2.)
    xy_vals_seq: Sequence[Tuple[Tuple[float, float, float], float]] = \
        [(x, superv_func(x) + n.rvs(size=1)[0]) for x in pts]

    ag = AdamGradient(
        learning_rate=0.5,
        decay1=0.9,
        decay2=0.999
    )
    ffs = [
        lambda x: x[0],
        lambda x: x[1],
        lambda x: x[2]
    ]

#     lfa = LinearFunctionApprox(
#         feature_functions=ffs,
#         adam_gradient=ag,
#         regularization_coeff=0.
#     )
# 
#     lfa_ds = lfa.direct_solve(xy_vals_seq)
#     print("Direct Solve")
#     pprint(lfa_ds.weights)
#     errors: np.ndarray = lfa_ds.evaluate(pts) - \
#         np.array([y for _, y in xy_vals_seq])
#     print("Mean Squared Error")
#     pprint(np.mean(errors * errors))
#     print()
# 
#     print("Linear Gradient Solve")
#     for _ in range(100):
#         print("Weights")
#         pprint(lfa.weights)
#         errors: np.ndarray = lfa.evaluate(pts) - \
#             np.array([y for _, y in xy_vals_seq])
#         print("Mean Squared Error")
#         pprint(np.mean(errors * errors))
#         lfa = lfa.update(xy_vals_seq)
#         print()

    ds = DNNSpec(
        neurons=[2],
        hidden_activation=lambda x: x,
        hidden_activation_deriv=lambda x: np.ones_like(x),
        output_activation=lambda x: x,
        output_activation_deriv=lambda x: np.ones_like(x)
    )

    dnna = DNNApprox(
        feature_functions=ffs,
        dnn_spec=ds,
        adam_gradient=ag,
        regularization_coeff=0.
    )
    print("DNN Gradient Solve")
    for _ in range(100):
        print("Weights")
        pprint(dnna.weights)
        errors: np.ndarray = dnna.evaluate(pts) - \
            np.array([y for _, y in xy_vals_seq])
        print("Mean Squared Error")
        pprint(np.mean(errors * errors))
        dnna = dnna.update(xy_vals_seq)
        print()

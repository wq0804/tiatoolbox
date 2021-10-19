# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# The Original Code is Copyright (C) 2021, TIALab, University of Warwick
# All rights reserved.
# ***** END GPL LICENSE BLOCK *****

"""Functions to help with constructing graphs."""

from collections import defaultdict
from numbers import Number
from typing import Dict, List, Optional, Union

import numpy as np
import torch
from numpy.typing import ArrayLike
from scipy.cluster import hierarchy
from scipy.spatial import Delaunay, cKDTree


def hybrid_clustered_graph(
    points: ArrayLike,
    features: ArrayLike,
    label: Optional[int] = None,
    lambda_d: Number = 3.0e-3,
    lambda_f: Number = 1.0e-3,
    lambda_h: Number = 0.8,
    connectivity_distance: Number = 4000,
    neighbour_search_radius: Number = 2000,
    feature_range_thresh: Number = 1e-4,
) -> Dict[str, ArrayLike]:
    """Build a graph via hybrid clustering in spatial and feature space.

    The graph is constructed via hybrid heirachical clustering followed
    by Delaunay triangulation of these cluster centroids.
    This is part of the SlideGraph pipeline but may be used to construct
    a graph in general from point coordinates and features.

    The clustering uses a distance kernel, ranging between 0 and 1,
    which is a weighted product of spatial distance (distance between
    coordinates in `points`, e.g. WSI location
    and feature-space distance (e.g. ResNet features).

    Points which are spatially further apart than
    `neighbour_search_radius` are given a similarity of 1 (most
    dissimilar). This significantly speeds up computation. This distance
    metric is then used to form clusters via hierachical/agglomerative
    clustering.

    Next, a Delaunay triangulation is applied to the clusters to connect
    the neighouring clusters. Only clusters which are closer than
    `connectivity_distance` in the spatial domain will be connected.

    Args:
        points (ArrayLike): A list of (x, y) spatial coordinates, e.g.
            pixel locations within a WSI.
        features (ArrayLike): A list of features associated with each
            coordinate in `points`. Must be the same length as `points`.
        lambda_d (Number): Spatial distance (d) weighting.
        lambda_f (Number): Feature distance (f) weighting.
        lambda_h (Number): Clustering distance threshold. Applied to
            the similarity kernel (1-fd). Ranges between 0 and 1.
            Defaults to 0.8. A good value for this parameter will depend
            on the intra-cluster variance.
        connectivity_distance (Number):
            Spatial distance threshold to consider points as connected
            during the Delaunay triangulation step.
        neighbour_search_radius (Number):
            Search radius (L2 norm) threshold for points to be
            considered as similar for clustering.
            Points with a spatial distance above this are not compared
            and have a similarity set to 1 (most dissimilar).
        feature_range_thresh (Number):
            Minimal range for which a feature is considered significant.
            Features which have a range less than this are ignored.
            Defaults to 1e-4.

    Returns:
        dict: A dictionary defining a graph for serialisation (e.g.
        JSON) or converting into a torch-geometric Data object where
        each node is the centroid (mean) if the features in a cluster.
            - :class:`numpy.ndarray` - x:
                Features of each node (mean of features in a cluster).
            - :class:`numpy.ndarray` - edge_index:
                Edge index matrix defining connectivity.
            - :py:obj:`Number` - y:
                The label of the graph.

    Example:
        >>> points = np.random.rand(99, 2) * 1000
        >>> features = np.array([
        ...     np.random.rand(11) * n
        ...     for n, _ in enumerate(points)
        ... ])
        >>> graph_dict = hybrid_clustered_graph(points, features)

    """
    # Remove features which do not change significantly between patches
    feature_ranges = np.max(features, axis=0) - np.min(features, axis=0)
    where_significant = feature_ranges > feature_range_thresh
    features = features[:, where_significant]

    # Build a kd-tree and rank neighbours according to the euclidean
    # distance (nearest -> farthest).
    ckdtree = cKDTree(points)
    neighbour_distances_ckd, neighbour_indexes_ckd = ckdtree.query(
        x=points, k=len(points)
    )

    # Initialise an empty 1-D condensed distance matrix.
    # For information on condensed distance matrices see:
    # noqa - https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.distance.pdist
    # noqa - https://docs.scipy.org/doc/scipy/reference/generated/scipy.cluster.hierarchy.linkage.html
    condensed_distance_matrix = np.zeros(int(len(points) * (len(points) - 1) / 2))

    # Find the similarity between pairs of patches
    index = 0
    for i in range(len(points) - 1):
        # Only consider neighbours which are inside of the radius
        # (neighbour_search_radius).
        neighbour_distances_singlepoint = neighbour_distances_ckd[i][
            neighbour_distances_ckd[i] < neighbour_search_radius
        ]
        neighbour_indexes_singlepoint = neighbour_indexes_ckd[i][
            : len(neighbour_distances_singlepoint)
        ]

        # Called f in the paper
        neighbour_feature_similarities = np.exp(
            -lambda_f
            * np.linalg.norm(
                features[i] - features[neighbour_indexes_singlepoint], axis=1
            )
        )
        # Called d in paper
        neighbour_distance_similarities = np.exp(
            -lambda_d * neighbour_distances_singlepoint
        )
        # 1 - product of similarities (1 - fd)
        # (1 = most un-similar 0 = most similar)
        neighbour_similarities = (
            1 - neighbour_feature_similarities * neighbour_distance_similarities
        )
        # Initialise similarity of coordinate i vs all coordinates to 1
        # (most un-similar).
        i_vs_all_similarities = np.ones(len(points))
        # Set the neighbours similarity to calculated values (similarity/fd)
        i_vs_all_similarities[neighbour_indexes_singlepoint] = neighbour_similarities
        i_vs_all_similarities = i_vs_all_similarities[i + 1 :]
        condensed_distance_matrix[
            index : index + len(i_vs_all_similarities)
        ] = i_vs_all_similarities
        index = index + len(i_vs_all_similarities)

    # Perform hierarchical clustering (using similarity as distance)
    linkage_matrix = hierarchy.linkage(condensed_distance_matrix, method="average")
    clusters = hierarchy.fcluster(linkage_matrix, lambda_h, criterion="distance")

    # Finding the xy centroid and average features for each cluster
    unique_clusters = list(set(clusters))
    point_centroids = []
    feature_centroids = []
    for c in unique_clusters:
        (idx,) = np.where(clusters == c)
        # Find the xy and feature space averages of the cluster
        point_centroids.append(np.round(points[idx, :].mean(axis=0)))
        feature_centroids.append(features[idx, :].mean(axis=0))
    point_centroids = np.array(point_centroids)
    feature_centroids = np.array(feature_centroids)

    adjacency_matrix = delaunay_adjacency(
        points=point_centroids,
        dthresh=connectivity_distance,
    )
    edge_index = affinity_to_edge_index(adjacency_matrix)

    result = {
        "x": feature_centroids,
        "edge_index": edge_index,
        "coords": point_centroids,
    }
    if label is not None:
        result["y"] = np.array([label])
    return result


def delaunay_adjacency(points: ArrayLike, dthresh: Number) -> ArrayLike:
    """Create an adjacency matrix via Delaunay triangulation from a list of coordinates.

    Points which are further apart than dthresh will not be connected.

    See https://en.wikipedia.org/wiki/Adjacency_matrix.

    Args:
        coordinates (ArrayLike): A nxm list of coordinates.
        dthresh (int): Distance threshold for triangulation.

    Returns:
        ArrayLike: Adjacency matrix of shape NxN where 1 indicates
            connected and 0 indicates unconnected.

    Example:
        >>> points = np.random.rand(100, 2)
        >>> adjacency = delaunay_adjacency(points)

    """
    # Validate inputs
    if not isinstance(dthresh, Number):
        raise TypeError("dthresh must be a number.")
    if len(points) < 4:
        raise ValueError("Points must have length >= 4.")
    if len(np.shape(points)) != 2:
        raise ValueError("Points must have an NxM shape.")
    # Apply Delaunay triangulation to the coordinates to get a
    # tessellation of triangles.
    tessellation = Delaunay(points)
    # Find all connected neighbours for each point in the set of
    # triangles. Starting with an empty dictionary.
    triangle_neighbours = defaultdict(set)
    # Iterate over each triplet of point indexes which denotes a
    # triangle within the tessellation.
    for index_triplet in tessellation.simplices:
        for index in index_triplet:
            connected = set(index_triplet)
            connected.remove(index)  # Do not allow connection to itself.
            triangle_neighbours[index] = triangle_neighbours[index].union(connected)
    # Initialise the nxn adjacency matrix with zeros.
    adjacency = np.zeros((len(points), len(points)))
    # Fill the adjacency matrix:
    for index in triangle_neighbours:
        neighbours = triangle_neighbours[index]
        neighbours = np.array(list(neighbours), dtype=int)
        kdtree = cKDTree(points[neighbours, :])
        nearby_neighbours = kdtree.query_ball_point(
            x=points[index],
            r=dthresh,
        )
        neighbours = neighbours[nearby_neighbours]
        adjacency[index, neighbours] = 1.0
        adjacency[neighbours, index] = 1.0
    # Return neighbours of each coordinate as an affinity (adjacency
    # in this case) matrix.
    return adjacency


def affinity_to_edge_index(
    affinity_matrix: Union[torch.Tensor, ArrayLike, List[List[Number]]],
    threshold: Number = 0.5,
) -> Union[torch.tensor, ArrayLike]:
    """Convert an affinity matrix (similarity matrix) to an edge index.

    Converts an NxN affinity matrix to a 2xM edge index, where M is
    the number of node pairs with a similarity greater than the
    threshold value (defaults to 0.5).

    Args:
        affinity_matrix: An NxN matrix of affinities between nodes.
        threshold (Number): Threshold above which to be considered
            connected. Defaults to 0.5.

    Returns:
        ArrayLike or torch.Tensor: The edge index of shape (2, M).

    Example:
        >>> points = np.random.rand(100, 2)
        >>> adjacency = delaunay_adjacency(points)
        >>> edge_index = affinity_to_edge_index(adjacency)

    """
    # Validate inputs
    input_shape = np.shape(affinity_matrix)
    if len(input_shape) != 2 or len(np.unique(input_shape)) != 1:
        raise ValueError("Input affinity_matrix must be square (NxN).")
    # Handle cases for pytorch and numpy inputs
    if isinstance(affinity_matrix, torch.Tensor):
        return (affinity_matrix > threshold).nonzero().t().contiguous()
    return np.ascontiguousarray(
        np.stack((affinity_matrix > threshold).nonzero(), axis=1).T
    )
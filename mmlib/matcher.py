from abc import ABC, abstractmethod

from dataclasses import dataclass


@dataclass
class Coordinate:
    """Represents a geographical coordinate."""

    latitude: float
    longitude: float

    def to_tuple(self) -> tuple[float, float]:
        """Convert the coordinate to a tuple representation.

        Returns:
        tuple[float, float]: The latitude and longitude as a tuple.
        """
        return (self.latitude, self.longitude)


@dataclass
class MatchResult:
    """Represents the result of a map matching operation."""

    points: list[Coordinate]
    edge_ids: list[str]


class BaseMatcher(ABC):
    """Matcher is a base class for map matching implementations."""

    @abstractmethod
    def map_match(self, gpx_points: str) -> MatchResult:
        """Map match the provided GPX points.

        Args:
            gpx_points (str): The GPX points to map match.

        Returns:
            MatchResult: The result of the map matching process.
        """
        ...


def graphhopper_matcher(base_url: str, gps_accuracy: int | None = None) -> BaseMatcher:
    """Create a GraphHopper matcher instance."""
    from mmlib.graphhopper.matcher import Matcher

    return Matcher(base_url=base_url, gps_accuracy=gps_accuracy)

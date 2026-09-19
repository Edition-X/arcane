"""Relationship commands — link and trace."""

from __future__ import annotations

import click

from arcane.cli._utils import ServiceContainer, create_container
from arcane.infra.db.ids import IdentifierResolutionError, resolve_entity_id


def _resolve(container: ServiceContainer, entity_type: str, entity_id: str) -> str:
    """Resolve an ID or prefix to the full stored ID, or exit with a usage error."""
    try:
        full_id = resolve_entity_id(container.db, entity_type, entity_id)
    except IdentifierResolutionError as exc:
        raise click.ClickException(str(exc)) from exc
    if full_id is None:
        raise click.ClickException(f"No {entity_type} found for {entity_id}")
    return full_id


@click.command()
@click.argument("source")
@click.argument("target")
@click.option(
    "--relation",
    required=True,
    type=click.Choice(["led_to", "informed_by", "resulted_in", "part_of", "supersedes", "references"]),
)
@click.option("--source-type", default="memory")
@click.option("--target-type", default="journey")
def link(source: str, target: str, relation: str, source_type: str, target_type: str) -> None:
    """Create a relationship between entities."""
    from arcane.domain.enums import RelationType
    from arcane.domain.models import Relationship

    with create_container() as container:
        source_id = _resolve(container, source_type, source)
        target_id = _resolve(container, target_type, target)
        rel = Relationship(
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation=RelationType(relation),
        )
        container.relationship_repo.insert(rel.model_dump())
    click.echo(f"Linked {source_type}:{source_id[:12]} --{relation}--> {target_type}:{target_id[:12]}")


@click.command()
@click.argument("entity_id")
@click.option("--type", "entity_type", default="journey")
@click.option("--depth", default=5)
def trace(entity_id: str, entity_type: str, depth: int) -> None:
    """Walk the relationship graph from an entity."""
    with create_container() as container:
        full_id = _resolve(container, entity_type, entity_id)
        rels = container.relationship_repo.trace(entity_type, full_id, max_depth=depth)

    if not rels:
        click.echo("No relationships found.")
        return

    click.echo(f"\nRelationship graph ({len(rels)} edges):")
    for r in rels:
        src = f"{r['source_type']}:{r['source_id'][:12]}"
        tgt = f"{r['target_type']}:{r['target_id'][:12]}"
        click.echo(f"  {src} --{r['relation']}--> {tgt}")

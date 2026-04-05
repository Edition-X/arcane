"""Relationship commands — link and trace."""

from __future__ import annotations

import click

from arcane.cli._utils import create_container


@click.command()
@click.argument("source")
@click.argument("target")
@click.option(
    "--relation", required=True,
    type=click.Choice(["led_to", "informed_by", "resulted_in", "part_of", "supersedes", "references"]),
)
@click.option("--source-type", default="memory")
@click.option("--target-type", default="journey")
def link(source: str, target: str, relation: str, source_type: str, target_type: str) -> None:
    """Create a relationship between entities."""
    from arcane.domain.enums import RelationType
    from arcane.domain.models import Relationship

    with create_container() as container:
        rel = Relationship(
            source_type=source_type, source_id=source,
            target_type=target_type, target_id=target,
            relation=RelationType(relation),
        )
        container.relationship_repo.insert(rel.model_dump())
    click.echo(f"Linked {source_type}:{source[:12]} --{relation}--> {target_type}:{target[:12]}")


@click.command()
@click.argument("entity_id")
@click.option("--type", "entity_type", default="journey")
@click.option("--depth", default=5)
def trace(entity_id: str, entity_type: str, depth: int) -> None:
    """Walk the relationship graph from an entity."""
    with create_container() as container:
        rels = container.relationship_repo.trace(entity_type, entity_id, max_depth=depth)

    if not rels:
        click.echo("No relationships found.")
        return

    click.echo(f"\nRelationship graph ({len(rels)} edges):")
    for r in rels:
        src = f"{r['source_type']}:{r['source_id'][:12]}"
        tgt = f"{r['target_type']}:{r['target_id'][:12]}"
        click.echo(f"  {src} --{r['relation']}--> {tgt}")

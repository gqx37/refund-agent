FROM neo4j:5.26-community

# Self-hosted Neo4j for the refund agent's semantic fact store (customers,
# orders, transactions, and shared-payment-method links for fraud detection).
#
# APOC core ships in the image under labs/; bake it into plugins/ at build time
# rather than downloading via NEO4J_PLUGINS on every boot.
RUN cp /var/lib/neo4j/labs/apoc-*-core.jar /var/lib/neo4j/plugins/

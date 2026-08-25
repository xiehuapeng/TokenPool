import asyncio

from sqlalchemy import func, select

from app.database.migrations import upgrade_database
from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing
from app.services.bootstrap import seed_initial_data


async def main() -> None:
    await upgrade_database()
    await seed_initial_data()

    async with SessionLocal() as session:
        model_count = await session.scalar(select(func.count(ModelConfig.id)))
        pricing_count = await session.scalar(select(func.count(ModelPricing.id)))
        rows = list(
            await session.execute(
                select(
                    ModelConfig.public_model,
                    ModelPricing.input_price,
                    ModelPricing.cached_input_price,
                    ModelPricing.output_price,
                )
                .join(ModelPricing, ModelPricing.model_config_id == ModelConfig.id)
                .order_by(ModelConfig.public_model)
            )
        )

    print(f"models={model_count} pricings={pricing_count}")
    for public_model, input_price, cached_price, output_price in rows:
        print(
            f"{public_model:28s} in={input_price} cached={cached_price} "
            f"out={output_price}"
        )


asyncio.run(main())

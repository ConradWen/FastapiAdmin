from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import MappedBase, ModelMixin, UserMixin


class PlatformTenantModel(ModelMixin, UserMixin):
    """租户定义（平台级，自身不受租户过滤——无 TenantMixin）。

    id=1 固定为「默认租户」：存量数据回填与超管平台面均引用它（server_default='1' 的对端）。
    """

    __tablename__: str = "platform_tenant"
    __table_args__: dict[str, str] = {"comment": "平台租户定义表"}

    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="租户名称")
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="租户编码")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None, comment="备注")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态: 0=正常,1=停用")


class PlatformUserTenantModel(MappedBase):
    """用户↔租户多对多（REQUIREMENTS v3.6：一个用户可关联多个租户，is_default 唯一默认）。

    sys_user.tenant_id 仍为「主归属/历史列」；登录决议取二者并集。
    """

    __tablename__: str = "platform_user_tenant"
    __table_args__: dict[str, str] = {"comment": "用户租户关联表"}

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True, comment="用户ID"
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("platform_tenant.id", ondelete="RESTRICT"), primary_key=True, comment="租户ID"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否默认租户")

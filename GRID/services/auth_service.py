from GRID.dtos.auth import LoginDto, SignupDto
from GRID.dtos.user import UserWithoutPasswordDto, UserCreateDto
from GRID.services import user_service
import bcrypt


# Hash a password using bcrypt
def hash_password(raw_password):
    pwd_bytes = raw_password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
    return hashed_password


## Check if the provided password matches the stored password (hashed)
#def verify_password(raw_password, hashed_password):
#    password_byte_enc = raw_password.encode('utf-8')
#    hashed_password_byte_enc = hashed_password.encode('utf-8')
#    return bcrypt.checkpw(password=password_byte_enc, hashed_password=hashed_password_byte_enc)


#async def login(dto: LoginDto) -> UserWithoutPasswordDto | None:
#    exist_user = await user_service.find_user_by_username(username=dto.username)
#    if exist_user:
#        is_password_correct = verify_password(raw_password=dto.password, hashed_password=exist_user.password)
#        print("IS PASSWORD CORRECT", is_password_correct)
#
#        if is_password_correct:
#            return UserWithoutPasswordDto.from_user_dto(user_dto=exist_user)
#
#        else:
#            return None


#async def signup(dto: SignupDto) -> UserWithoutPasswordDto:
#    exist_user = await user_service.find_user_by_username(username=dto.username)
#    if exist_user:
#        return UserWithoutPasswordDto.from_user_dto(user_dto=exist_user)
#
#    else:
#        hashed_password = hash_password(raw_password=dto.password)
#        created_user = await user_service.create_user(
#            dto=UserCreateDto(username=dto.username, password=hashed_password)
#        )
#        print("[CREATED USER]", created_user)
#        return UserWithoutPasswordDto.from_user_dto(user_dto=created_user)
